"""RESQ Verification Agent: Bounded, evidence-driven autonomous verification loop."""

import time
from typing import Any, Optional
from resq.agent.models import (

    AgentActionName,
    AgentBudget,
    AgentCompletionStatus,
    AgentDecision,
    AgentObservation,
    AgentState,
    AgentStep,
)
from resq.agent.tools import ToolRegistry
from resq.agent.verifier import DeterministicTruthGate
from resq.config import Settings, get_settings
from resq.engine.failure_analyzer import FailureAnalyzer
from resq.engine.patch_applier import PatchApplier
from resq.execution.base import ExecutionEnvironment
from resq.llm.base import LLMProvider
from resq.llm.factory import get_llm_provider
from resq.models import (
    CandidatePatch,
    ExecutionResult,
    FailureArtifact,
    Verdict,
    VerificationJob,
    VerificationRun,
)


class RESQVerificationAgent:
    """Specialized AI agent for developer software verification.

    Implements:
    OBSERVE -> REASON -> SELECT ACTION -> EXECUTE TOOL -> EVALUATE RESULT -> UPDATE STATE -> CONTINUE OR STOP

    Invariants:
    1. Bounded decision loop with strict budgets (cycles, tool calls, time, patch attempts).
    2. Zero unauthorized host mutation: source code is read-only.
    3. Mandatory Docker sandbox for test execution.
    4. Deterministic Truth Gate: model claims never decide verdicts.
    5. Auditable trace of all decisions and observations.
    """

    def __init__(
        self,
        execution_env: ExecutionEnvironment,
        llm_provider: Optional[LLMProvider] = None,
        settings: Optional[Settings] = None,
        failure_analyzer: Optional[FailureAnalyzer] = None,
        patch_applier: Optional[PatchApplier] = None,
        budget: Optional[AgentBudget] = None,
    ):
        self.settings = settings or get_settings()
        self.execution_env = execution_env
        self.llm_provider = llm_provider or get_llm_provider(self.settings)
        self.failure_analyzer = failure_analyzer or FailureAnalyzer()
        self.patch_applier = patch_applier or PatchApplier()

        max_cycles = getattr(self.settings, "agent_max_cycles", 8)
        max_tool_calls = getattr(self.settings, "agent_max_tool_calls", 12)
        max_patches = min(self.settings.max_repair_cycles, 2)

        self.budget = budget or AgentBudget(
            max_decision_cycles=max_cycles,
            max_tool_calls=max_tool_calls,
            max_patch_attempts=max_patches,
            max_execution_time_seconds=float(self.settings.max_execution_timeout_seconds * 3),
        )

        self.tools = ToolRegistry(
            execution_env=self.execution_env,
            llm_provider=self.llm_provider,
            failure_analyzer=self.failure_analyzer,
            patch_applier=self.patch_applier,
            max_output_chars=self.budget.max_output_chars,
        )

    def run(
        self,
        source_code: str,
        test_code: str,
        target_filename: str = "target.py",
        test_filename: str = "test_target.py",
        objective: str = "Investigate failure, evaluate defect hypothesis, and verify candidate patch against edge-case invariants",
    ) -> VerificationJob:
        """Executes the autonomous verification agent loop.

        Returns:
            VerificationJob containing runs, agent_steps, and independent final verdict.
        """
        start_time = time.perf_counter()

        provider_name = getattr(self.llm_provider, "provider_name", "mock")
        if hasattr(self.llm_provider, "settings") and getattr(self.llm_provider.settings, "llm_provider", None):
            provider_name = self.llm_provider.settings.llm_provider

        execution_mode = "live_gemini" if "gemini" in str(provider_name).lower() else "mock"

        job = VerificationJob(
            target_filename=target_filename,
            source_code=source_code,
            invariants_code=test_code,
            current_status="RUNNING_BASELINE",
            objective=objective,
            execution_mode=execution_mode,
        )

        state = AgentState(
            job_id=job.id,
            objective=objective,
            target_filename=target_filename,
            test_filename=test_filename,
            source_code=source_code,
            invariants_code=test_code,
            remaining_cycles=self.budget.max_decision_cycles,
            remaining_tool_calls=self.budget.max_tool_calls,
            max_patch_attempts=self.budget.max_patch_attempts,
        )

        context: dict[str, Any] = {
            "source_code": source_code,
            "invariants_code": test_code,
            "target_filename": target_filename,
            "test_filename": test_filename,
        }

        agent_steps: list[AgentStep] = []
        runs: list[VerificationRun] = []

        stop_reason: Optional[str] = None
        cycle = 0
        tool_calls_count = 0
        patch_attempts_count = 0
        timed_out = False
        infra_error = False
        llm_error = False

        while cycle < self.budget.max_decision_cycles:
            cycle += 1
            step_start = time.perf_counter()

            # 1. Check time budget
            elapsed = time.perf_counter() - start_time
            if elapsed >= self.budget.max_execution_time_seconds:
                stop_reason = f"Budget exhausted: Execution time exceeded {self.budget.max_execution_time_seconds:.1f}s."
                break

            # 2. Check tool call budget
            if tool_calls_count >= self.budget.max_tool_calls:
                stop_reason = f"Budget exhausted: Tool call count exceeded {self.budget.max_tool_calls} calls."
                break

            # 3. Update state snapshot for decision
            state.cycle_index = cycle
            state.remaining_cycles = self.budget.max_decision_cycles - cycle
            state.tool_calls_count = tool_calls_count
            state.remaining_tool_calls = self.budget.max_tool_calls - tool_calls_count
            state.patch_attempts = patch_attempts_count
            state.has_baseline_run = "baseline_execution_result" in context
            if state.has_baseline_run:
                b_res: ExecutionResult = context["baseline_execution_result"]
                state.baseline_passed = b_res.exit_code == 0
                state.baseline_exit_code = b_res.exit_code

            state.current_failure = context.get("current_failure")
            state.current_patch = context.get("current_patch")
            state.patch_syntax_valid = context.get("patch_syntax_valid")
            if "reverification_verdict" in context:
                state.reverification_passed = context["reverification_verdict"] == Verdict.VERIFIED

            # 4. OBSERVE & REASON -> Model selects action
            try:
                if hasattr(self.llm_provider, "decide_action"):
                    decision: AgentDecision = self.llm_provider.decide_action(state)
                else:
                    # Fallback deterministic controller if provider does not implement decide_action
                    decision = self._deterministic_fallback_decision(state)
            except Exception as exc:
                llm_error = True
                stop_reason = f"LLM Provider error: {str(exc)}"
                error_step = AgentStep(
                    cycle_index=cycle,
                    decision=AgentDecision(
                        action=AgentActionName.STOP.value,
                        reason="Provider error encountered during decision cycle.",
                        expected_observation="Halt agent execution.",
                        completion_status=AgentCompletionStatus.BLOCKED,
                    ),
                    observation=AgentObservation(
                        tool_name="llm_provider",
                        success=False,
                        output=str(exc),
                        summary=f"LLM decision failure: {str(exc)}",
                        evidence_payload={"error": "LLM_ERROR"},
                    ),
                    duration_seconds=time.perf_counter() - step_start,
                )
                agent_steps.append(error_step)
                break

            # Check for control action 'stop'
            if decision.action == AgentActionName.STOP.value or decision.completion_status in (
                AgentCompletionStatus.COMPLETED,
                AgentCompletionStatus.NEEDS_HUMAN_REVIEW,
                AgentCompletionStatus.BLOCKED,
                AgentCompletionStatus.INCONCLUSIVE,
            ):
                stop_reason = decision.reason or f"Agent requested stop with status: {decision.completion_status.value}"
                stop_step = AgentStep(
                    cycle_index=cycle,
                    decision=decision,
                    observation=AgentObservation(
                        tool_name="control",
                        success=True,
                        summary=f"Agent completed verification loop: {stop_reason}",
                    ),
                    duration_seconds=time.perf_counter() - step_start,
                )
                agent_steps.append(stop_step)
                break

            # 5. Safety & Permission Gate
            action_name = decision.action
            if not self.tools.is_registered(action_name):
                # Unknown / unregistered tool rejected
                obs = AgentObservation(
                    tool_name=action_name,
                    success=False,
                    summary=f"Permission Gate: Action '{action_name}' is not registered or permitted.",
                    evidence_payload={"error": "UNREGISTERED_TOOL"},
                )
                step = AgentStep(
                    cycle_index=cycle,
                    decision=decision,
                    observation=obs,
                    duration_seconds=time.perf_counter() - step_start,
                )
                agent_steps.append(step)
                state.recent_steps.append(step)
                continue

            if action_name == AgentActionName.GENERATE_CANDIDATE_PATCH.value:
                if patch_attempts_count >= self.budget.max_patch_attempts:
                    obs = AgentObservation(
                        tool_name=action_name,
                        success=False,
                        summary=f"Budget constraint: Maximum patch attempts ({self.budget.max_patch_attempts}) reached.",
                        evidence_payload={"error": "PATCH_BUDGET_EXHAUSTED"},
                    )
                    step = AgentStep(
                        cycle_index=cycle,
                        decision=decision,
                        observation=obs,
                        duration_seconds=time.perf_counter() - step_start,
                    )
                    agent_steps.append(step)
                    state.recent_steps.append(step)
                    continue
                patch_attempts_count += 1

            # 6. EXECUTE TOOL
            tool_calls_count += 1
            observation = self.tools.execute(action_name, decision.arguments, context)

            # Check if execution triggered infra or timeout flags
            if (
                observation.evidence_payload.get("error") == "INFRASTRUCTURE_ERROR"
                or observation.evidence_payload.get("exit_code") == 125
            ):
                infra_error = True
            if observation.evidence_payload.get("timed_out"):
                timed_out = True

            if action_name == AgentActionName.ANALYZE_FAILURE.value:
                art = context.get("current_failure")
                if runs and runs[0].run_type == "BASELINE" and art:
                    runs[0].failure_artifact = art

            elif action_name == AgentActionName.RUN_BASELINE_TESTS.value:
                b_res: Optional[ExecutionResult] = context.get("baseline_execution_result")
                fail_art = context.get("current_failure")
                if b_res:
                    if b_res.exit_code == 0:
                        verdict = Verdict.NO_FAILURE_FOUND
                    elif b_res.timed_out:
                        verdict = Verdict.TIMEOUT_EXCEEDED
                    elif b_res.exit_code == 125:
                        verdict = Verdict.INFRASTRUCTURE_ERROR
                        infra_error = True
                    else:
                        verdict = Verdict.REJECTED_STILL_FAILS

                    runs.append(
                        VerificationRun(
                            job_id=job.id,
                            run_type="BASELINE",
                            cycle_index=0,
                            execution_result=b_res,
                            failure_artifact=fail_art,
                            verdict=verdict,
                        )
                    )
                elif observation.evidence_payload.get("error") == "INFRASTRUCTURE_ERROR":
                    infra_res = ExecutionResult(
                        exit_code=125,
                        stdout="",
                        stderr=str(observation.output or ""),
                        timed_out=False,
                        duration_seconds=0.0,
                    )
                    context["baseline_execution_result"] = infra_res
                    runs.append(
                        VerificationRun(
                            job_id=job.id,
                            run_type="BASELINE",
                            cycle_index=0,
                            execution_result=infra_res,
                            verdict=Verdict.INFRASTRUCTURE_ERROR,
                        )
                    )

            elif action_name == AgentActionName.RUN_VERIFICATION_TESTS.value:
                rv_res: Optional[ExecutionResult] = context.get("reverification_execution_result")
                rv_verdict: Optional[Verdict] = context.get("reverification_verdict")
                cand_patch: Optional[CandidatePatch] = context.get("current_patch")
                unified_diff: Optional[str] = context.get("unified_diff")

                if rv_verdict:
                    if rv_verdict == Verdict.INFRASTRUCTURE_ERROR:
                        infra_error = True
                    runs.append(
                        VerificationRun(
                            job_id=job.id,
                            run_type="REVERIFICATION",
                            cycle_index=patch_attempts_count,
                            execution_result=rv_res,
                            candidate_patch=cand_patch,
                            unified_diff=unified_diff,
                            verdict=rv_verdict,
                        )
                    )

            elif action_name in (AgentActionName.GENERATE_CANDIDATE_PATCH.value, AgentActionName.VALIDATE_CANDIDATE_PATCH.value):
                # If candidate patch has a syntax error, record REJECTED_SYNTAX_ERROR run
                syntax_valid = observation.evidence_payload.get("syntax_valid")
                cand_patch = context.get("current_patch")
                if syntax_valid is False and cand_patch and not any(r.verdict == Verdict.REJECTED_SYNTAX_ERROR for r in runs):
                    runs.append(
                        VerificationRun(
                            job_id=job.id,
                            run_type="REVERIFICATION",
                            cycle_index=patch_attempts_count,
                            candidate_patch=cand_patch,
                            verdict=Verdict.REJECTED_SYNTAX_ERROR,
                        )
                    )


            step = AgentStep(
                cycle_index=cycle,
                decision=decision,
                observation=observation,
                duration_seconds=time.perf_counter() - step_start,
            )
            agent_steps.append(step)
            state.recent_steps.append(step)

            # Check if baseline clean -> can terminate immediately
            if action_name == AgentActionName.RUN_BASELINE_TESTS.value:
                if context.get("baseline_execution_result") and context["baseline_execution_result"].exit_code == 0:
                    stop_reason = "Baseline tests passed completely. No defect or edge case discovered."
                    break

            # Check if re-verification verified -> can stop
            if action_name == AgentActionName.RUN_VERIFICATION_TESTS.value:
                if context.get("reverification_verdict") == Verdict.VERIFIED:
                    stop_reason = "Empirically verified: candidate patch passed reproducer and all regression checks in sandbox."
                    break

            # If infrastructure failure occurred, halt
            if infra_error:
                stop_reason = "Halted due to infrastructure error in sandbox execution."
                break

        if not stop_reason and cycle >= self.budget.max_decision_cycles:
            stop_reason = f"Decision cycle budget exhausted ({self.budget.max_decision_cycles} cycles)."

        # 8. Deterministic Truth Gate computes the authoritative final verdict
        final_verdict, verdict_explanation = DeterministicTruthGate.evaluate(
            baseline_result=context.get("baseline_execution_result"),
            failure_artifact=context.get("current_failure"),
            patch_syntax_valid=context.get("patch_syntax_valid"),
            reverify_result=context.get("reverification_execution_result"),
            reverify_verdict=context.get("reverification_verdict"),
            agent_completion_status=AgentCompletionStatus.COMPLETED,
            timed_out=timed_out,
            infrastructure_error=infra_error,
            llm_error=llm_error,
            budget_exhausted=(cycle >= self.budget.max_decision_cycles),
        )

        job.final_verdict = final_verdict
        job.termination_reason = f"{stop_reason} [{verdict_explanation}]"
        job.agent_steps = agent_steps
        job.runs = runs

        # Decouple status from verdict
        normal_completion_verdicts = {
            Verdict.VERIFIED,
            Verdict.NO_FAILURE_FOUND,
            Verdict.REJECTED_STILL_FAILS,
            Verdict.REJECTED_REGRESSION,
            Verdict.REJECTED_SYNTAX_ERROR,
            Verdict.INSUFFICIENT_EVIDENCE,
        }
        if final_verdict in normal_completion_verdicts:
            job.current_status = "COMPLETED"
        else:
            job.current_status = "FAILED"

        return job

    def _deterministic_fallback_decision(self, state: AgentState) -> AgentDecision:
        """Deterministic policy fallback when no active LLM decision engine is present."""
        if not state.has_baseline_run:
            return AgentDecision(
                action=AgentActionName.RUN_BASELINE_TESTS.value,
                reason="Execute baseline tests to determine if a defect exists in target module.",
                expected_observation="Exit code and test failure trace if a defect is present.",
            )

        if state.baseline_passed:
            return AgentDecision(
                action=AgentActionName.STOP.value,
                reason="Baseline tests completed cleanly without discovering any failures.",
                expected_observation="Conclude verification with NO_FAILURE_FOUND.",
                completion_status=AgentCompletionStatus.COMPLETED,
            )

        if not state.current_failure:
            return AgentDecision(
                action=AgentActionName.ANALYZE_FAILURE.value,
                reason="Analyze baseline failure output to extract reproducible test case and counterexample.",
                expected_observation="Parsed FailureArtifact with failing input and traceback.",
            )

        if state.current_failure and not state.current_failure.is_reproducible:
            return AgentDecision(
                action=AgentActionName.SUMMARIZE_EVIDENCE.value,
                arguments={"assessment": "Failure could not be deterministically reproduced."},
                reason="Failure evidence is unparseable or non-reproducible.",
                expected_observation="Structured evidence summary.",
                completion_status=AgentCompletionStatus.INCONCLUSIVE,
            )

        if not state.current_patch:
            return AgentDecision(
                action=AgentActionName.GENERATE_CANDIDATE_PATCH.value,
                reason="Synthesize targeted candidate patch based on reproducible failure evidence.",
                expected_observation="Syntactically valid Python code addressing the defect.",
            )

        if state.patch_syntax_valid is None:
            return AgentDecision(
                action=AgentActionName.VALIDATE_CANDIDATE_PATCH.value,
                reason="Validate candidate patch syntax and generate unified diff before execution.",
                expected_observation="Confirmation of Python AST syntax validity.",
            )

        if state.patch_syntax_valid is False:
            return AgentDecision(
                action=AgentActionName.STOP.value,
                reason="Candidate patch has invalid syntax. Rejecting patch.",
                expected_observation="Conclude verification with REJECTED_SYNTAX_ERROR.",
                completion_status=AgentCompletionStatus.COMPLETED,
            )

        if state.reverification_passed is None:
            return AgentDecision(
                action=AgentActionName.RUN_VERIFICATION_TESTS.value,
                reason="Re-verify candidate patch in isolated Docker sandbox against baseline and properties.",
                expected_observation="Pass/fail result of candidate patch.",
            )

        return AgentDecision(
            action=AgentActionName.STOP.value,
            reason="All verification checks have concluded.",
            expected_observation="Terminal verdict and evidence summary.",
            completion_status=AgentCompletionStatus.COMPLETED,
        )

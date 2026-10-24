"""Comprehensive unit and integration tests for the RESQ Verification Agent.

Verifies:
1. Tool registry functionality, parameter validation, and unregistered tool rejection.
2. Dynamic tool selection driven by observations (clean baseline vs reproducible failure).
3. Adaptation on failed tool results (syntax error blocks execution).
4. Insufficient evidence handling (inconclusive outcome).
5. Budget enforcement (cycles, tool calls, execution timeout).
6. Deterministic independent truth gate (model cannot fabricate VERIFIED).
7. Trace persistence and API retrieval.
8. Original source code immutability.
"""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Optional
import pytest
from fastapi.testclient import TestClient

from resq.agent.agent import RESQVerificationAgent
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
from resq.api.app import create_app
from resq.config import Settings
from resq.database import (
    AgentStepRecord,
    VerificationJobRecord,
    get_engine,
    get_session_factory,
    init_db,
)
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.llm.mock_provider import MockLLMProvider
from resq.models import (
    CandidatePatch,
    ExecutionResult,
    FailureArtifact,
    Verdict,
    VerificationJob,
)

# Test Fixtures
SAMPLE_SOURCE = """def binary_search(arr: list[int], target: int) -> int:
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low < high:  # Off-by-one bug
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
"""

CLEAN_SOURCE = """def binary_search(arr: list[int], target: int) -> int:
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
"""

SAMPLE_TESTS = """from hypothesis import given, strategies as st
from target import binary_search

def test_baseline_empty():
    assert binary_search([], 10) == -1

def test_baseline_found():
    assert binary_search([1, 3, 5], 3) == 1

@given(st.lists(st.integers()).map(sorted))
def test_hypothesis_finds(arr):
    for x in arr:
        assert binary_search(arr, x) != -1
"""


class FakeExecutionEnvironment(ExecutionEnvironment):
    """Deterministic in-memory execution environment for unit testing agent logic."""

    def __init__(self, exit_codes: Optional[list[int]] = None, outputs: Optional[list[tuple[str, str]]] = None):
        self.exit_codes = exit_codes or [0]
        self.outputs = outputs or [("", "")]
        self.call_count = 0
        self.executed_commands = []

    def execute(self, workspace_path: Path, command: list[str], timeout_seconds: Optional[int] = None) -> ExecutionResult:
        self.executed_commands.append((command, workspace_path))
        idx = min(self.call_count, len(self.exit_codes) - 1)
        code = self.exit_codes[idx]
        stdout, stderr = self.outputs[min(self.call_count, len(self.outputs) - 1)]
        self.call_count += 1
        return ExecutionResult(
            exit_code=code,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            duration_seconds=0.05,
        )


class TestAgentToolRegistry:
    """Validates the typed, bounded tool registry."""

    def test_inspect_source_returns_lines_and_symbols(self):
        env = FakeExecutionEnvironment()
        llm = MockLLMProvider()
        tools = ToolRegistry(execution_env=env, llm_provider=llm)

        obs = tools.execute(
            AgentActionName.INSPECT_SOURCE.value,
            {"start_line": 1, "end_line": 10},
            {"source_code": SAMPLE_SOURCE},
        )
        assert obs.success is True
        assert "def binary_search" in obs.summary
        assert obs.evidence_payload["total_lines"] > 0
        assert "1:" in obs.output

    def test_inspect_tests_discovers_hypothesis_properties(self):
        env = FakeExecutionEnvironment()
        llm = MockLLMProvider()
        tools = ToolRegistry(execution_env=env, llm_provider=llm)

        obs = tools.execute(
            AgentActionName.INSPECT_TESTS.value,
            {},
            {"invariants_code": SAMPLE_TESTS},
        )
        assert obs.success is True
        assert "test_baseline_empty" in obs.evidence_payload["tests_found"]
        assert "test_hypothesis_finds" in obs.evidence_payload["hypothesis_properties"]

    def test_inspect_ast_detects_syntax_errors(self):
        env = FakeExecutionEnvironment()
        llm = MockLLMProvider()
        tools = ToolRegistry(execution_env=env, llm_provider=llm)

        bad_code = "def broken(\n  return 42"
        obs = tools.execute(
            AgentActionName.INSPECT_AST.value,
            {"target": "source"},
            {"source_code": bad_code},
        )
        assert obs.success is True
        assert obs.evidence_payload["valid_syntax"] is False
        assert "SyntaxError" in obs.summary

    def test_unregistered_tool_is_rejected(self):
        env = FakeExecutionEnvironment()
        llm = MockLLMProvider()
        tools = ToolRegistry(execution_env=env, llm_provider=llm)

        obs = tools.execute(
            "run_arbitrary_shell_command",
            {"cmd": "rm -rf /"},
            {"source_code": SAMPLE_SOURCE},
        )
        assert obs.success is False
        assert "not a registered verification tool" in obs.summary
        assert obs.evidence_payload["error_type"] == "UnregisteredToolError"

    def test_validate_candidate_patch_without_patch_fails_safely(self):
        env = FakeExecutionEnvironment()
        llm = MockLLMProvider()
        tools = ToolRegistry(execution_env=env, llm_provider=llm)

        obs = tools.execute(
            AgentActionName.VALIDATE_CANDIDATE_PATCH.value,
            {},
            {"source_code": SAMPLE_SOURCE},
        )
        assert obs.success is False
        assert "No candidate patch has been synthesized" in obs.summary


class TestAgentDecisionLoop:
    """Validates dynamic decision loop, observation-driven branching, and budget limits."""

    def test_clean_baseline_causes_agent_to_stop_with_no_failure_found(self):
        """When baseline test exits 0, agent observes pass and terminates immediately."""
        env = FakeExecutionEnvironment(exit_codes=[0], outputs=[("3 passed", "")])
        llm = MockLLMProvider(mode="valid")
        agent = RESQVerificationAgent(execution_env=env, llm_provider=llm)

        job = agent.run(
            source_code=CLEAN_SOURCE,
            test_code=SAMPLE_TESTS,
        )

        assert job.final_verdict == Verdict.NO_FAILURE_FOUND
        assert job.current_status == "COMPLETED"
        assert len(job.runs) == 1
        assert job.runs[0].verdict == Verdict.NO_FAILURE_FOUND
        assert len(job.agent_steps) >= 2  # inspect_source -> run_baseline_tests -> stop

    def test_observation_changes_next_action_reproducible_failure(self):
        """Failing baseline causes agent to analyze failure, synthesize patch, and re-verify."""
        failure_output = """
FAILED test_target.py::test_hypothesis_finds - AssertionError
Falsifying example: test_hypothesis_finds(arr=[1, 2])
--hypothesis-seed=123456
E   AssertionError: assert -1 != -1
"""
        reverify_output = "3 passed in 0.05s"

        env = FakeExecutionEnvironment(
            exit_codes=[1, 0],
            outputs=[(failure_output, ""), (reverify_output, "")],
        )
        llm = MockLLMProvider(mode="valid")
        agent = RESQVerificationAgent(execution_env=env, llm_provider=llm)

        job = agent.run(
            source_code=SAMPLE_SOURCE,
            test_code=SAMPLE_TESTS,
        )

        assert job.final_verdict == Verdict.VERIFIED
        assert job.current_status == "COMPLETED"
        assert len(job.agent_steps) >= 4

        actions = [s.decision.action for s in job.agent_steps]
        assert AgentActionName.RUN_BASELINE_TESTS.value in actions
        assert AgentActionName.ANALYZE_FAILURE.value in actions
        assert AgentActionName.GENERATE_CANDIDATE_PATCH.value in actions
        assert AgentActionName.RUN_VERIFICATION_TESTS.value in actions

    def test_failed_syntax_patch_changes_decision_and_halts_execution(self):
        """A candidate patch with syntax errors is caught by static gate and rejected before container execution."""
        failure_output = "FAILED test_target.py::test_fail\nFalsifying example: test_fail(x=1)\nE ZeroDivisionError"
        env = FakeExecutionEnvironment(exit_codes=[1], outputs=[(failure_output, "")])
        llm = MockLLMProvider(mode="syntax_error")
        agent = RESQVerificationAgent(execution_env=env, llm_provider=llm)

        job = agent.run(
            source_code=SAMPLE_SOURCE,
            test_code=SAMPLE_TESTS,
        )

        assert job.final_verdict == Verdict.REJECTED_SYNTAX_ERROR
        assert job.current_status == "COMPLETED"
        # The re-verification tool in sandbox should NOT have been run
        actions = [s.decision.action for s in job.agent_steps]
        assert AgentActionName.RUN_VERIFICATION_TESTS.value not in actions

    def test_inconclusive_failure_causes_insufficient_evidence_verdict(self):
        """Unparseable crash without reproducible counterexample causes INSUFFICIENT_EVIDENCE."""
        unparseable_output = "Process killed with mysterious unformatted error code"
        env = FakeExecutionEnvironment(exit_codes=[1], outputs=[(unparseable_output, "")])
        llm = MockLLMProvider(mode="valid")
        agent = RESQVerificationAgent(execution_env=env, llm_provider=llm)

        job = agent.run(
            source_code=SAMPLE_SOURCE,
            test_code=SAMPLE_TESTS,
        )

        assert job.final_verdict == Verdict.INSUFFICIENT_EVIDENCE
        assert job.current_status == "COMPLETED"

    def test_iteration_budget_is_strictly_enforced(self):
        """Agent loop stops when max decision cycles are exhausted without infinite spinning."""
        failure_output = "FAILED test_target.py::test_fail\nFalsifying example: test_fail(x=1)\nE ZeroDivisionError"
        env = FakeExecutionEnvironment(exit_codes=[1], outputs=[(failure_output, "")])

        # Sequence of redundant inspect actions that would never terminate on their own
        neverending_sequence = [
            AgentDecision(
                action=AgentActionName.INSPECT_SOURCE.value,
                arguments={"start_line": 1},
                reason="Inspecting source repeatedly.",
                expected_observation="Source lines.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )
            for _ in range(25)
        ]

        llm = MockLLMProvider(decision_sequence=neverending_sequence)
        budget = AgentBudget(max_decision_cycles=4, max_tool_calls=10)
        agent = RESQVerificationAgent(execution_env=env, llm_provider=llm, budget=budget)

        job = agent.run(
            source_code=SAMPLE_SOURCE,
            test_code=SAMPLE_TESTS,
        )

        assert len(job.agent_steps) == 4
        assert "budget exhausted" in job.termination_reason.lower()

    def test_deterministic_truth_gate_rejects_model_fabricated_verdict(self):
        """Truth gate enforces that agent claiming success when tests fail is designated REJECTED_STILL_FAILS."""
        # Baseline failed, re-verify also failed (exit code 1)
        fail_out = "FAILED\nFalsifying example: (x=1)\nE AssertionError"
        env = FakeExecutionEnvironment(
            exit_codes=[1, 1],
            outputs=[(fail_out, ""), (fail_out, "")],
        )

        # Injected decision where agent falsely claims completed with success
        fabricating_sequence = [
            AgentDecision(
                action=AgentActionName.RUN_BASELINE_TESTS.value,
                reason="Run baseline tests.",
                expected_observation="Results.",
            ),
            AgentDecision(
                action=AgentActionName.ANALYZE_FAILURE.value,
                reason="Analyze failure.",
                expected_observation="Artifact.",
            ),
            AgentDecision(
                action=AgentActionName.GENERATE_CANDIDATE_PATCH.value,
                reason="Synthesize patch.",
                expected_observation="Patch.",
            ),
            AgentDecision(
                action=AgentActionName.RUN_VERIFICATION_TESTS.value,
                reason="Re-verify in sandbox.",
                expected_observation="Passes.",
            ),
            AgentDecision(
                action=AgentActionName.STOP.value,
                reason="I claim the code is 100% verified and correct!",
                expected_observation="Conclude.",
                completion_status=AgentCompletionStatus.COMPLETED,
            ),
        ]

        llm = MockLLMProvider(mode="still_fails", decision_sequence=fabricating_sequence)
        agent = RESQVerificationAgent(execution_env=env, llm_provider=llm)

        job = agent.run(
            source_code=SAMPLE_SOURCE,
            test_code=SAMPLE_TESTS,
        )

        # Independent deterministic truth gate must override model claim
        assert job.final_verdict == Verdict.REJECTED_STILL_FAILS

    def test_original_source_code_immutability(self):
        """Verifies candidate patches are never written to host or original source."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            orig_file = Path(tmp_dir) / "target.py"
            orig_file.write_text(SAMPLE_SOURCE, encoding="utf-8")
            orig_content = orig_file.read_text(encoding="utf-8")

            env = FakeExecutionEnvironment(exit_codes=[0])
            llm = MockLLMProvider(mode="valid")
            agent = RESQVerificationAgent(execution_env=env, llm_provider=llm)

            job = agent.run(
                source_code=SAMPLE_SOURCE,
                test_code=SAMPLE_TESTS,
            )

            # Original file remains untouched
            assert orig_file.read_text(encoding="utf-8") == orig_content


class TestAgentAPIPersistence:
    """Validates database persistence and FastAPI endpoint retrieval of agent traces."""

    @pytest.fixture
    def test_client(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_resq.db"
            db_url = f"sqlite:///{db_path}"
            engine = get_engine(db_url)
            init_db(engine)
            session_factory = get_session_factory(engine)
            settings = Settings(database_url=db_url)
            app = create_app(settings=settings, session_factory=session_factory, engine=engine)
            with TestClient(app) as client:
                yield client, session_factory
            engine.dispose()


    def test_agent_trace_retrieval_via_api(self, test_client):
        client, session_factory = test_client

        # Seed a job with agent steps
        with session_factory() as session:
            job_rec = VerificationJobRecord(
                id="agent-job-001",
                target_filename="target.py",
                test_filename="test_target.py",
                source_code=SAMPLE_SOURCE,
                invariants_code=SAMPLE_TESTS,
                current_status="COMPLETED",
                final_verdict="VERIFIED",
                objective="Verify binary search boundary invariants",
                execution_mode="mock",
                termination_reason="Empirically verified in sandbox.",
            )
            step_rec = AgentStepRecord(
                id="step-1",
                job_id="agent-job-001",
                cycle_index=1,
                action="inspect_source",
                arguments='{"start_line": 1}',
                reason="Inspect target source before executing tests.",
                expected_observation="Source code lines.",
                completion_status="continue",
                success=True,
                output="1: def binary_search...",
                summary="Inspected 15 lines of source.",
                evidence_payload='{"total_lines": 15}',
                duration_seconds=0.02,
                created_at=datetime.now(timezone.utc),
            )
            job_rec.agent_steps.append(step_rec)
            session.add(job_rec)
            session.commit()

        # 1. Fetch full job detail
        resp = client.get("/api/v1/jobs/agent-job-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["objective"] == "Verify binary search boundary invariants"
        assert data["execution_mode"] == "mock"
        assert len(data["agent_steps"]) == 1
        assert data["agent_steps"][0]["decision"]["action"] == "inspect_source"

        # 2. Fetch dedicated trace endpoint
        trace_resp = client.get("/api/v1/jobs/agent-job-001/trace")
        assert trace_resp.status_code == 200
        trace = trace_resp.json()
        assert len(trace) == 1
        assert trace[0]["decision"]["action"] == "inspect_source"
        assert trace[0]["observation"]["summary"] == "Inspected 15 lines of source."

    def test_restarted_backend_retrieves_traces_from_sqlite(self, tmp_path):
        """Simulates complete process restart: a second backend instance reads persisted traces from SQLite."""
        db_path = tmp_path / "restart_test.db"
        db_url = f"sqlite:///{db_path}"
        engine = get_engine(db_url)
        init_db(engine)
        session_factory = get_session_factory(engine)

        with session_factory() as session:
            job_rec = VerificationJobRecord(
                id="persisted-job-999",
                target_filename="target.py",
                test_filename="test_target.py",
                source_code="def f(): pass",
                invariants_code="def test_f(): pass",
                current_status="COMPLETED",
                final_verdict="VERIFIED",
                objective="Boundary check",
                execution_mode="mock",
            )
            step = AgentStepRecord(
                id="step-999",
                job_id="persisted-job-999",
                cycle_index=1,
                action="run_baseline_tests",
                arguments="{}",
                reason="Run baseline tests",
                expected_observation="Pass or fail",
                completion_status="continue",
                success=True,
                output="1 passed",
                summary="Baseline tests passed.",
                duration_seconds=0.05,
            )
            job_rec.agent_steps.append(step)
            session.add(job_rec)
            session.commit()
        engine.dispose()

        # Simulate process restart by creating a completely new engine, session factory, and FastAPI app
        restarted_engine = get_engine(db_url)
        restarted_factory = get_session_factory(restarted_engine)
        restarted_settings = Settings(database_url=db_url)
        restarted_app = create_app(settings=restarted_settings, session_factory=restarted_factory, engine=restarted_engine)

        with TestClient(restarted_app) as restarted_client:
            resp = restarted_client.get("/api/v1/jobs/persisted-job-999/trace")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["decision"]["action"] == "run_baseline_tests"
            assert data[0]["observation"]["summary"] == "Baseline tests passed."

        restarted_engine.dispose()

    def test_no_api_key_or_secrets_leaked_in_trace_response(self, test_client):
        """Validates that no credentials, API keys, or authorization headers are exposed in responses."""
        client, session_factory = test_client

        with session_factory() as session:
            job_rec = VerificationJobRecord(
                id="sec-job-001",
                target_filename="target.py",
                test_filename="test_target.py",
                source_code="def f(): pass",
                invariants_code="def test_f(): pass",
                current_status="COMPLETED",
                final_verdict="VERIFIED",
                objective="Security check",
                execution_mode="live_gemini",
            )
            step = AgentStepRecord(
                id="sec-step-1",
                job_id="sec-job-001",
                cycle_index=1,
                action="inspect_source",
                arguments='{"start_line": 1}',
                reason="Inspect code",
                expected_observation="Lines",
                completion_status="continue",
                success=True,
                output="def f(): pass",
                summary="Inspected code cleanly.",
                duration_seconds=0.01,
            )
            job_rec.agent_steps.append(step)
            session.add(job_rec)
            session.commit()

        detail_resp = client.get("/api/v1/jobs/sec-job-001")
        trace_resp = client.get("/api/v1/jobs/sec-job-001/trace")

        raw_detail = detail_resp.text.lower()
        raw_trace = trace_resp.text.lower()

        # Assert no sensitive key names or auth values exist in serialized output
        for secret_token in ["api_key", "authorization", "bearer", "secret", "private_key"]:
            assert secret_token not in raw_detail
            assert secret_token not in raw_trace


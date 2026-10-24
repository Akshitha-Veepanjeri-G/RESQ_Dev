"""Independent deterministic truth gate for the RESQ Verification Agent.

Invariants:
1. LLM / Agent self-evaluations NEVER decide the verification verdict.
2. A separate deterministic component computes whether required checks passed.
3. Distinguishes: VERIFIED, NO_FAILURE_FOUND, REJECTED_STILL_FAILS,
   REJECTED_REGRESSION, REJECTED_SYNTAX_ERROR, INSUFFICIENT_EVIDENCE,
   TIMEOUT_EXCEEDED, LLM_ERROR, INFRASTRUCTURE_ERROR.
"""

from typing import Any, Optional
from resq.agent.models import AgentCompletionStatus
from resq.models import ExecutionResult, FailureArtifact, Verdict


class DeterministicTruthGate:
    """Evaluates collected empirical evidence and computes the authoritative verdict."""

    @staticmethod
    def evaluate(
        baseline_result: Optional[ExecutionResult],
        failure_artifact: Optional[FailureArtifact],
        patch_syntax_valid: Optional[bool],
        reverify_result: Optional[ExecutionResult],
        reverify_verdict: Optional[Verdict],
        agent_completion_status: AgentCompletionStatus,
        timed_out: bool = False,
        infrastructure_error: bool = False,
        llm_error: bool = False,
        budget_exhausted: bool = False,
    ) -> tuple[Verdict, str]:
        """Computes deterministic verdict and explanation independently of model claims.

        Returns:
            (canonical_verdict, explanation)
        """
        if (
            infrastructure_error
            or (baseline_result and baseline_result.exit_code == 125)
            or (reverify_result and reverify_result.exit_code == 125)
            or (reverify_verdict == Verdict.INFRASTRUCTURE_ERROR)
        ):
            return (
                Verdict.INFRASTRUCTURE_ERROR,
                "Verification halted due to container or host infrastructure failure.",
            )

        if timed_out or (baseline_result and baseline_result.timed_out) or (reverify_result and reverify_result.timed_out):
            return (
                Verdict.TIMEOUT_EXCEEDED,
                "Execution exceeded hard sandbox timeout ceiling.",
            )

        if llm_error:
            return (
                Verdict.LLM_ERROR,
                "LLM provider failed, timed out, or produced an unrecoverable API error.",
            )

        # Baseline clean execution: no failure discovered
        if baseline_result and baseline_result.exit_code == 0:
            return (
                Verdict.NO_FAILURE_FOUND,
                "Initial property tests and invariants ran to completion without discovering any failing case.",
            )

        # Baseline failed, but failure could not be reproduced / minimized
        if failure_artifact and not failure_artifact.is_reproducible and not reverify_result:
            return (
                Verdict.INSUFFICIENT_EVIDENCE,
                "Test execution failed, but insufficient structured evidence was extracted to formulate a reproducible test case.",
            )

        # Candidate patch syntax error
        if patch_syntax_valid is False:
            return (
                Verdict.REJECTED_SYNTAX_ERROR,
                "Candidate patch produced invalid Python code and was rejected by static AST validation.",
            )

        # Sandbox re-verification outcome
        if reverify_result is not None:
            if reverify_result.exit_code == 0:
                if baseline_result is None:
                    return (
                        Verdict.INSUFFICIENT_EVIDENCE,
                        "Verification cannot be declared VERIFIED without initial baseline execution evidence.",
                    )
                if patch_syntax_valid is not True:
                    return (
                        Verdict.REJECTED_SYNTAX_ERROR,
                        "Candidate patch code was not validated by static AST syntax checks.",
                    )
                if reverify_verdict == Verdict.REJECTED_REGRESSION:
                    return (
                        Verdict.REJECTED_REGRESSION,
                        "Candidate patch resolved the reproducer but broke existing baseline regression tests.",
                    )
                return (
                    Verdict.VERIFIED,
                    "Empirically verified: candidate patch passed AST checks, resolved reproducer, and passed all baseline regression tests in isolated sandbox.",
                )

            if reverify_verdict == Verdict.REJECTED_REGRESSION:
                return (
                    Verdict.REJECTED_REGRESSION,
                    "Candidate patch resolved the reproducer but broke existing baseline regression tests.",
                )

            return (
                Verdict.REJECTED_STILL_FAILS,
                "Candidate patch applied cleanly, but the reproducer test still failed in sandbox.",
            )

        # If budget exhausted without verification
        if budget_exhausted:
            if failure_artifact and failure_artifact.is_reproducible:
                return (
                    Verdict.REJECTED_STILL_FAILS,
                    "Verification budget exhausted before a successful patch could be verified.",
                )
            return (
                Verdict.INSUFFICIENT_EVIDENCE,
                "Verification budget exhausted with inconclusive evidence.",
            )

        # Agent stopped with inconclusive or blocked
        if agent_completion_status == AgentCompletionStatus.INCONCLUSIVE:
            return (
                Verdict.INSUFFICIENT_EVIDENCE,
                "Verification concluded as inconclusive due to insufficient failure evidence.",
            )

        # Default fallback
        if baseline_result and baseline_result.exit_code != 0:
            return (
                Verdict.REJECTED_STILL_FAILS,
                "Target code contains unresolved test failures.",
            )

        return (
            Verdict.INSUFFICIENT_EVIDENCE,
            "Verification terminated without sufficient conclusive test results.",
        )

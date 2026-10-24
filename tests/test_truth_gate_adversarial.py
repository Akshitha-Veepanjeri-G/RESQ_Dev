"""Adversarial validation suite for DeterministicTruthGate.

Validates that model assertions, hallucinated claims, missing evidence,
contradictory records, and infrastructure faults cannot override objective empirical verification.
"""

import pytest
from resq.agent.models import AgentCompletionStatus
from resq.agent.verifier import DeterministicTruthGate
from resq.models import ExecutionResult, FailureArtifact, Verdict


class TestDeterministicTruthGateAdversarial:
    """Rigorous tests proving the model can never override empirical verification."""

    def test_model_claims_success_while_verification_test_fails(self):
        """Model claims victory, but container exit code is non-zero -> REJECTED_STILL_FAILS."""
        base_res = ExecutionResult(exit_code=1, stdout="Falsifying example", stderr="", duration_seconds=1.0)
        reverify_res = ExecutionResult(exit_code=1, stdout="AssertionError: assert False", stderr="", duration_seconds=1.0)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=base_res,
            failure_artifact=FailureArtifact(is_reproducible=True),
            patch_syntax_valid=True,
            reverify_result=reverify_res,
            reverify_verdict=Verdict.REJECTED_STILL_FAILS,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
        )

        assert verdict == Verdict.REJECTED_STILL_FAILS
        assert verdict != Verdict.VERIFIED
        assert "still failed" in reason

    def test_model_claims_success_without_any_verification_run(self):
        """Model claims completed without running verification tests -> REJECTED_STILL_FAILS."""
        base_res = ExecutionResult(exit_code=1, stdout="Failure", stderr="", duration_seconds=1.0)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=base_res,
            failure_artifact=FailureArtifact(is_reproducible=True),
            patch_syntax_valid=True,
            reverify_result=None,
            reverify_verdict=None,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
        )

        assert verdict == Verdict.REJECTED_STILL_FAILS
        assert verdict != Verdict.VERIFIED

    def test_model_claims_success_after_baseline_already_passed(self):
        """Clean baseline that already passed must yield NO_FAILURE_FOUND, never VERIFIED repair."""
        clean_base = ExecutionResult(exit_code=0, stdout="3 passed in 0.1s", stderr="", duration_seconds=0.1)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=clean_base,
            failure_artifact=None,
            patch_syntax_valid=None,
            reverify_result=None,
            reverify_verdict=None,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
        )

        assert verdict == Verdict.NO_FAILURE_FOUND
        assert verdict != Verdict.VERIFIED
        assert "without discovering any failing case" in reason

    def test_model_claims_success_after_infrastructure_error(self):
        """Infrastructure errors (exit 125 or flag) must yield INFRASTRUCTURE_ERROR, never VERIFIED."""
        infra_base = ExecutionResult(exit_code=125, stdout="", stderr="docker: daemon unreachable", duration_seconds=0.0)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=infra_base,
            failure_artifact=None,
            patch_syntax_valid=True,
            reverify_result=None,
            reverify_verdict=None,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
            infrastructure_error=True,
        )

        assert verdict == Verdict.INFRASTRUCTURE_ERROR
        assert verdict != Verdict.VERIFIED

    def test_verification_succeeds_even_when_model_claims_failure(self):
        """Empirical verification in container is authoritative: exit code 0 verifies even if model doubts."""
        base_res = ExecutionResult(exit_code=1, stdout="Failed", stderr="", duration_seconds=1.0)
        reverify_res = ExecutionResult(exit_code=0, stdout="1 passed in 0.2s", stderr="", duration_seconds=0.2)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=base_res,
            failure_artifact=FailureArtifact(is_reproducible=True),
            patch_syntax_valid=True,
            reverify_result=reverify_res,
            reverify_verdict=Verdict.VERIFIED,
            agent_completion_status=AgentCompletionStatus.BLOCKED,  # Model claims blocked
        )

        assert verdict == Verdict.VERIFIED
        assert "Empirically verified" in reason

    def test_missing_baseline_evidence_prevents_verified(self):
        """Re-verification exit 0 without baseline evidence cannot be VERIFIED."""
        reverify_res = ExecutionResult(exit_code=0, stdout="passed", stderr="", duration_seconds=0.2)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=None,
            failure_artifact=None,
            patch_syntax_valid=True,
            reverify_result=reverify_res,
            reverify_verdict=Verdict.VERIFIED,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
        )

        assert verdict == Verdict.INSUFFICIENT_EVIDENCE
        assert verdict != Verdict.VERIFIED
        assert "without initial baseline execution evidence" in reason

    def test_patch_with_invalid_syntax_cannot_be_verified(self):
        """Candidate patch with syntax error must yield REJECTED_SYNTAX_ERROR, never VERIFIED."""
        base_res = ExecutionResult(exit_code=1, stdout="Failed", stderr="", duration_seconds=1.0)
        reverify_res = ExecutionResult(exit_code=0, stdout="passed", stderr="", duration_seconds=0.2)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=base_res,
            failure_artifact=FailureArtifact(is_reproducible=True),
            patch_syntax_valid=False,  # Syntax error
            reverify_result=reverify_res,
            reverify_verdict=Verdict.VERIFIED,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
        )

        assert verdict == Verdict.REJECTED_SYNTAX_ERROR
        assert verdict != Verdict.VERIFIED

    def test_regression_verdict_cannot_be_overridden_to_verified(self):
        """Regression verdict in sandbox must yield REJECTED_REGRESSION, never VERIFIED."""
        base_res = ExecutionResult(exit_code=1, stdout="Failed", stderr="", duration_seconds=1.0)
        reverify_res = ExecutionResult(exit_code=1, stdout="Baseline regression: test_original failed", stderr="", duration_seconds=0.5)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=base_res,
            failure_artifact=FailureArtifact(is_reproducible=True),
            patch_syntax_valid=True,
            reverify_result=reverify_res,
            reverify_verdict=Verdict.REJECTED_REGRESSION,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
        )

        assert verdict == Verdict.REJECTED_REGRESSION
        assert verdict != Verdict.VERIFIED

    def test_timeout_takes_precedence_over_model_assertions(self):
        """Timed out execution must yield TIMEOUT_EXCEEDED."""
        base_res = ExecutionResult(exit_code=124, stdout="", stderr="Timed out", timed_out=True, duration_seconds=10.0)

        verdict, reason = DeterministicTruthGate.evaluate(
            baseline_result=base_res,
            failure_artifact=None,
            patch_syntax_valid=True,
            reverify_result=None,
            reverify_verdict=None,
            agent_completion_status=AgentCompletionStatus.COMPLETED,
            timed_out=True,
        )

        assert verdict == Verdict.TIMEOUT_EXCEEDED
        assert verdict != Verdict.VERIFIED

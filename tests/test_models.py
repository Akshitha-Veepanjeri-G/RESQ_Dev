"""Unit tests for RESQ Dev domain models, canonical verdicts, and configuration."""

import pytest
from pydantic import ValidationError
from resq.config import Settings
from resq.models import (
    CandidatePatch,
    ExecutionResult,
    FailureArtifact,
    Verdict,
    VerificationJob,
    VerificationRun,
)


class TestVerdictTaxonomy:
    """Validates the authoritative nine-verdict taxonomy."""

    def test_canonical_verdicts_count_and_members(self):
        expected_verdicts = {
            "VERIFIED",
            "NO_FAILURE_FOUND",
            "REJECTED_STILL_FAILS",
            "REJECTED_REGRESSION",
            "REJECTED_SYNTAX_ERROR",
            "INSUFFICIENT_EVIDENCE",
            "TIMEOUT_EXCEEDED",
            "LLM_ERROR",
            "INFRASTRUCTURE_ERROR",
        }
        actual_verdicts = {v.value for v in Verdict}
        assert actual_verdicts == expected_verdicts
        assert len(Verdict) == 9

    def test_verdict_is_string_enum(self):
        assert isinstance(Verdict.VERIFIED, str)
        assert Verdict.VERIFIED == "VERIFIED"


class TestDomainModels:
    """Validates instantiation, serialization, and constraints of domain models."""

    def test_execution_result_defaults_and_serialization(self):
        result = ExecutionResult(
            exit_code=0,
            stdout="test passed",
            stderr="",
            duration_seconds=1.23,
        )
        assert result.exit_code == 0
        assert result.timed_out is False
        assert result.duration_seconds == 1.23

        json_data = result.model_dump_json()
        restored = ExecutionResult.model_validate_json(json_data)
        assert restored == result

    def test_failure_artifact_structure(self):
        artifact = FailureArtifact(
            failing_input={"x": 0, "s": "\x00"},
            exception_type="ZeroDivisionError",
            assertion_message="division by zero",
            traceback_raw="Traceback ...",
            seed=42,
            is_reproducible=True,
        )
        assert artifact.is_reproducible is True
        assert artifact.seed == 42
        assert artifact.failing_input == {"x": 0, "s": "\x00"}

        # Empty artifact with defaults
        empty_artifact = FailureArtifact()
        assert empty_artifact.is_reproducible is False
        assert empty_artifact.failing_input is None

    def test_candidate_patch_structure(self):
        patch = CandidatePatch(
            patch_code="def add(a, b): return a + b\n",
            explanation="Fixed off-by-one error",
            provider_name="mock",
        )
        assert patch.provider_name == "mock"
        assert "def add" in patch.patch_code

    def test_verification_run_lifecycle(self):
        run = VerificationRun(
            job_id="test-job-uuid",
            run_type="BASELINE",
            cycle_index=0,
            verdict=Verdict.REJECTED_STILL_FAILS,
        )
        assert run.job_id == "test-job-uuid"
        assert run.verdict == Verdict.REJECTED_STILL_FAILS
        assert run.id is not None
        assert run.executed_at is not None

    def test_verification_job_defaults_and_roundtrip(self):
        job = VerificationJob(
            source_code="def buggy(x): return x / (x - 1)\n",
            invariants_code="def test_buggy(): pass\n",
        )
        assert job.current_status == "PENDING"
        assert job.final_verdict is None
        assert len(job.runs) == 0

        # Add a run
        run = VerificationRun(
            job_id=job.id,
            run_type="BASELINE",
            verdict=Verdict.VERIFIED,
        )
        job.runs.append(run)
        job.final_verdict = Verdict.VERIFIED
        job.current_status = "COMPLETED"

        json_str = job.model_dump_json()
        restored = VerificationJob.model_validate_json(json_str)
        assert restored.id == job.id
        assert restored.final_verdict == Verdict.VERIFIED
        assert len(restored.runs) == 1
        assert restored.runs[0].verdict == Verdict.VERIFIED


class TestSettingsValidation:
    """Validates configuration models and safety boundaries."""

    def test_settings_defaults(self, default_settings):
        assert default_settings.docker_image_name == "resq-sandbox:latest"
        assert default_settings.max_execution_timeout_seconds == 10
        assert default_settings.docker_memory_limit == "512m"
        assert default_settings.docker_cpu_limit == 1.0
        assert default_settings.docker_pids_limit == 64
        assert default_settings.max_repair_cycles == 1
        assert default_settings.llm_provider == "mock"

    def test_timeout_bounds_validation(self):
        # Negative or 0 timeout should fail
        with pytest.raises(ValidationError):
            Settings(max_execution_timeout_seconds=0)

        with pytest.raises(ValidationError):
            Settings(max_execution_timeout_seconds=-5)

        # Timeout exceeding 60 seconds should fail
        with pytest.raises(ValidationError):
            Settings(max_execution_timeout_seconds=61)

        # Valid timeout
        s = Settings(max_execution_timeout_seconds=30)
        assert s.max_execution_timeout_seconds == 30

    def test_repair_cycles_bounded_validation(self):
        # Less than 1 should fail
        with pytest.raises(ValidationError):
            Settings(max_repair_cycles=0)

        # More than 2 (hard maximum for bounded repair) should fail
        with pytest.raises(ValidationError):
            Settings(max_repair_cycles=3)

        # Valid repair cycles (1 or 2)
        s1 = Settings(max_repair_cycles=1)
        assert s1.max_repair_cycles == 1
        s2 = Settings(max_repair_cycles=2)
        assert s2.max_repair_cycles == 2

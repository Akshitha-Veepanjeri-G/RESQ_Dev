"""Domain models and canonical verdict taxonomy for RESQ Dev."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """The nine mutually exclusive canonical verdicts of RESQ Dev."""

    # Deterministic Success
    VERIFIED = "VERIFIED"

    # Deterministic Completion without Failure
    NO_FAILURE_FOUND = "NO_FAILURE_FOUND"

    # Deterministic Test Failures
    REJECTED_STILL_FAILS = "REJECTED_STILL_FAILS"
    REJECTED_REGRESSION = "REJECTED_REGRESSION"

    # Static AST Syntax Failure
    REJECTED_SYNTAX_ERROR = "REJECTED_SYNTAX_ERROR"

    # Engine Evidence Limitations
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    # Resource Ceiling Exceeded
    TIMEOUT_EXCEEDED = "TIMEOUT_EXCEEDED"

    # External Provider Failures
    LLM_ERROR = "LLM_ERROR"

    # Host & Container Infrastructure Failures
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


class ExecutionResult(BaseModel):
    """Low-level execution output captured from the Docker container."""

    exit_code: int = Field(description="Process exit code.")
    stdout: str = Field(default="", description="Captured standard output.")
    stderr: str = Field(default="", description="Captured standard error.")
    timed_out: bool = Field(default=False, description="Whether execution was terminated due to timeout.")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Duration of execution in seconds.")


class FailureArtifact(BaseModel):
    """Structured evidence extracted from a failing test execution."""

    failing_input: Optional[Any] = Field(
        default=None,
        description="Minimized failing argument or input dictionary from Hypothesis.",
    )
    exception_type: Optional[str] = Field(
        default=None,
        description="Class name of the raised exception (e.g., IndexError, ZeroDivisionError).",
    )
    assertion_message: Optional[str] = Field(
        default=None,
        description="Captured assertion message or error description.",
    )
    traceback_raw: str = Field(
        default="",
        description="Full, un-truncated stack trace from pytest.",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Hypothesis random seed enabling deterministic local reproduction.",
    )
    is_reproducible: bool = Field(
        default=False,
        description="Whether sufficient evidence was extracted to formulate a deterministic reproducer.",
    )


class CandidatePatch(BaseModel):
    """A candidate code patch synthesized by an LLM provider."""

    patch_code: str = Field(description="The suggested Python code or replacement function.")
    explanation: str = Field(default="", description="Optional rationale or analysis provided by model.")
    raw_model_response: str = Field(default="", description="Raw response text from provider.")
    provider_name: str = Field(default="mock", description="Name of LLM provider that synthesized this patch.")


class VerificationRun(BaseModel):
    """Record of a single execution cycle within a verification job."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str = Field(description="Parent verification job UUID.")
    run_type: str = Field(
        default="BASELINE",
        description="Run category: 'BASELINE' or 'REVERIFICATION'.",
    )
    cycle_index: int = Field(
        default=0,
        ge=0,
        description="Repair cycle index (0 for baseline, 1 or 2 for bounded repair).",
    )
    execution_result: Optional[ExecutionResult] = None
    failure_artifact: Optional[FailureArtifact] = None
    candidate_patch: Optional[CandidatePatch] = None
    unified_diff: Optional[str] = Field(
        default=None,
        description="Standard unified diff between original source and candidate patch.",
    )
    verdict: Verdict = Field(description="Outcome verdict of this specific run.")
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationJob(BaseModel):
    """Lifecycle entity for a verification task on a target module."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_filename: str = Field(default="target.py", description="Name of target Python module.")
    source_code: str = Field(description="Original user source code under verification.")
    invariants_code: str = Field(default="", description="Property-based tests or invariant specifications.")
    current_status: str = Field(default="PENDING", description="Current lifecycle state of the job.")
    final_verdict: Optional[Verdict] = Field(default=None, description="Final deterministic verdict.")
    runs: list[VerificationRun] = Field(default_factory=list, description="Ordered history of execution runs.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

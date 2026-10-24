"""Request and response schemas and lifecycle status enum for RESQ Dev API."""

from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
from resq.models import Verdict

# Regex strictly enforcing basename-only Python filenames (no paths, no traversal, no ADS)
FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+\.py$")


class JobStatus(str, Enum):
    """Lifecycle progression states for a verification job."""

    PENDING = "PENDING"
    RUNNING_BASELINE = "RUNNING_BASELINE"
    REPAIR_CYCLE_1 = "REPAIR_CYCLE_1"
    REPAIR_CYCLE_2 = "REPAIR_CYCLE_2"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


def validate_python_filename(filename: str, field_name: str) -> str:
    """Validates that a filename is a strict basename-only Python filename."""
    if not filename or not isinstance(filename, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    if "/" in filename or "\\" in filename or ".." in filename or ":" in filename:
        raise ValueError(f"{field_name} must not contain path separators, traversal, or colons")
    if not FILENAME_REGEX.match(filename):
        raise ValueError(f"{field_name} must be a valid Python filename ending in .py (e.g., target.py)")
    return filename


class JobCreateRequest(BaseModel):
    """Payload for submitting a Python verification job."""

    source_code: str = Field(
        ...,
        min_length=1,
        max_length=131_072,
        description="Original Python source code under verification (max 128 KiB).",
    )
    invariants_code: str = Field(
        ...,
        min_length=1,
        max_length=131_072,
        description="Hypothesis property tests or unit test harness (max 128 KiB).",
    )
    target_filename: str = Field(
        default="target.py",
        max_length=100,
        description="Basename of the target source module.",
    )
    test_filename: str = Field(
        default="test_target.py",
        max_length=100,
        description="Basename of the test suite module.",
    )

    @field_validator("target_filename")
    @classmethod
    def validate_target(cls, v: str) -> str:
        return validate_python_filename(v, "target_filename")

    @field_validator("test_filename")
    @classmethod
    def validate_test(cls, v: str) -> str:
        return validate_python_filename(v, "test_filename")


class JobSummaryResponse(BaseModel):
    """Summary record of a verification job."""

    job_id: str
    target_filename: str
    test_filename: str
    current_status: JobStatus
    final_verdict: Optional[Verdict] = None
    created_at: datetime


class ExecutionResultResponse(BaseModel):
    """Output from an execution run."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


class FailureArtifactResponse(BaseModel):
    """Extracted failure evidence."""

    failing_input: Optional[Any] = None
    exception_type: Optional[str] = None
    assertion_message: Optional[str] = None
    traceback_raw: str = ""
    seed: Optional[int] = None
    is_reproducible: bool = False


class CandidatePatchResponse(BaseModel):
    """Candidate patch details."""

    patch_code: str
    explanation: str = ""
    provider_name: str = "mock"


class VerificationRunResponse(BaseModel):
    """Details of a single execution cycle."""

    id: str
    job_id: str
    run_type: str
    cycle_index: int
    verdict: Verdict
    unified_diff: Optional[str] = None
    execution_result: Optional[ExecutionResultResponse] = None
    failure_artifact: Optional[FailureArtifactResponse] = None
    candidate_patch: Optional[CandidatePatchResponse] = None
    executed_at: datetime


class AgentDecisionResponse(BaseModel):
    """Decision produced during an agent cycle."""

    action: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    expected_observation: str
    completion_status: str = "continue"


class AgentObservationResponse(BaseModel):
    """Observation and evidence captured after tool execution."""

    tool_name: str
    success: bool
    output: Optional[Any] = None
    summary: str
    evidence_payload: dict[str, Any] = Field(default_factory=dict)


class AgentStepResponse(BaseModel):
    """Record of a single agent decision cycle."""

    id: str
    cycle_index: int
    decision: AgentDecisionResponse
    observation: AgentObservationResponse
    duration_seconds: float = 0.0
    timestamp: datetime


class JobDetailResponse(BaseModel):
    """Detailed record of a verification job, omitting raw submitted code by default."""

    id: str
    target_filename: str
    test_filename: str
    current_status: JobStatus
    final_verdict: Optional[Verdict] = None
    objective: str = "Investigate failure, evaluate defect hypothesis, and verify candidate patch against edge-case invariants"
    execution_mode: str = "mock"
    termination_reason: Optional[str] = None
    runs: list[VerificationRunResponse] = Field(default_factory=list)
    agent_steps: list[AgentStepResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime



class JobListResponse(BaseModel):
    """Paginated list of verification job summaries."""

    jobs: list[JobSummaryResponse] = Field(default_factory=list)
    total: int


class HealthResponse(BaseModel):
    """System and infrastructure health status."""

    status: str  # "ok" | "degraded" | "unhealthy"
    database_connected: bool
    docker_available: bool
    llm_provider: str = "mock"
    credential_configured: bool = False
    version: str = "0.1.0"

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


class AgentDecision(BaseModel):
    """Structured decision produced by the agent controller / LLM provider."""

    action: str = Field(description="Name of the registered tool or control decision ('stop').")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Schema-validated arguments for tool.")
    reason: str = Field(description="Concise, evidence-based explanation for choosing this action.")
    expected_observation: str = Field(description="What information or outcome the agent expects.")
    completion_status: str = Field(default="continue", description="continue, completed, needs_human_review, blocked, or inconclusive.")


class AgentObservation(BaseModel):
    """Structured observation and evidence captured after tool execution."""

    tool_name: str = Field(description="Tool that was executed.")
    success: bool = Field(default=True, description="Whether the tool executed without error.")
    output: Any = Field(default=None, description="Raw or bounded output from tool.")
    summary: str = Field(default="", description="Human-readable summary of the observation.")
    evidence_payload: dict[str, Any] = Field(default_factory=dict, description="Structured key-value evidence.")


class AgentStep(BaseModel):
    """Record of a single decision cycle in the agent loop."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cycle_index: int = Field(ge=0, description="Cycle index.")
    decision: AgentDecision = Field(description="Decision made by the agent.")
    observation: AgentObservation = Field(description="Result observed after tool execution.")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Time spent in this cycle.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationJob(BaseModel):
    """Lifecycle entity for a verification task on a target module."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_filename: str = Field(default="target.py", description="Name of target Python module.")
    source_code: str = Field(description="Original user source code under verification.")
    invariants_code: str = Field(default="", description="Property-based tests or invariant specifications.")
    current_status: str = Field(default="PENDING", description="Current lifecycle state of the job.")
    final_verdict: Optional[Verdict] = Field(default=None, description="Final deterministic verdict.")
    objective: str = Field(
        default="Investigate failure, evaluate defect hypothesis, and verify candidate patch against edge-case invariants",
        description="Verification goal.",
    )
    execution_mode: str = Field(default="mock", description="Execution mode: 'mock' or 'live_gemini'.")
    termination_reason: Optional[str] = Field(default=None, description="Detailed explanation of why the agent terminated.")
    runs: list[VerificationRun] = Field(default_factory=list, description="Ordered history of execution runs.")
    agent_steps: list[AgentStep] = Field(default_factory=list, description="Ordered history of agent decision cycles.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


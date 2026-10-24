"""Domain models for the RESQ Verification Agent."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid
from pydantic import BaseModel, Field

from resq.models import CandidatePatch, ExecutionResult, FailureArtifact, Verdict


class AgentActionName(str, Enum):
    """Registered tool actions available to the RESQ Verification Agent."""

    INSPECT_SOURCE = "inspect_source"
    INSPECT_TESTS = "inspect_tests"
    RUN_BASELINE_TESTS = "run_baseline_tests"
    ANALYZE_FAILURE = "analyze_failure"
    INSPECT_AST = "inspect_ast"
    RUN_HYPOTHESIS_ANALYSIS = "run_hypothesis_analysis"
    GENERATE_CANDIDATE_PATCH = "generate_candidate_patch"
    VALIDATE_CANDIDATE_PATCH = "validate_candidate_patch"
    RUN_VERIFICATION_TESTS = "run_verification_tests"
    SUMMARIZE_EVIDENCE = "summarize_evidence"

    # Control decisions
    STOP = "stop"


class AgentCompletionStatus(str, Enum):
    """Lifecycle status reported by or evaluated for the agent."""

    CONTINUE = "continue"
    COMPLETED = "completed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


class AgentDecision(BaseModel):
    """Structured decision produced by the agent controller / LLM provider."""

    action: str = Field(
        description="Name of the registered tool or control decision ('stop').",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Schema-validated arguments for the selected tool.",
    )
    reason: str = Field(
        description="Concise, evidence-based explanation for choosing this action.",
    )
    expected_observation: str = Field(
        description="What information or outcome the agent expects to observe.",
    )
    completion_status: AgentCompletionStatus = Field(
        default=AgentCompletionStatus.CONTINUE,
        description="Whether to continue the cycle or request termination.",
    )


class AgentObservation(BaseModel):
    """Structured observation and evidence captured after tool execution."""

    tool_name: str = Field(description="Tool that was executed.")
    success: bool = Field(default=True, description="Whether the tool executed without error.")
    output: Any = Field(default=None, description="Raw or bounded output from tool.")
    summary: str = Field(default="", description="Human-readable summary of the observation.")
    evidence_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured key-value evidence extracted from the tool result.",
    )


class AgentStep(BaseModel):
    """Record of a single decision cycle in the agent loop."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cycle_index: int = Field(ge=0, description="Cycle index (0-based or 1-based).")
    decision: AgentDecision = Field(description="Decision made by the agent.")
    observation: AgentObservation = Field(description="Result observed after tool execution.")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Time spent in this cycle.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentBudget(BaseModel):
    """Configurable iteration and resource budget for the verification agent."""

    max_decision_cycles: int = Field(default=8, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=30)
    max_execution_time_seconds: float = Field(default=120.0, ge=5.0, le=300.0)
    max_patch_attempts: int = Field(default=2, ge=1, le=3)
    max_output_chars: int = Field(default=65536, ge=1024, le=1048576)


class AgentState(BaseModel):
    """Structured snapshot of task state supplied to the agent for decision making."""

    job_id: str
    objective: str = Field(
        default="Investigate failure, evaluate defect hypothesis, and verify candidate patch against edge-case invariants",
    )
    target_filename: str = "target.py"
    test_filename: str = "test_target.py"
    source_code: str
    invariants_code: str

    cycle_index: int = 0
    remaining_cycles: int = 8
    tool_calls_count: int = 0
    remaining_tool_calls: int = 12
    patch_attempts: int = 0
    max_patch_attempts: int = 2

    # Evidence state
    has_baseline_run: bool = False
    baseline_passed: Optional[bool] = None
    baseline_exit_code: Optional[int] = None

    current_failure: Optional[FailureArtifact] = None
    current_patch: Optional[CandidatePatch] = None
    patch_syntax_valid: Optional[bool] = None
    reverification_passed: Optional[bool] = None

    # Step history
    recent_steps: list[AgentStep] = Field(default_factory=list)

    # Termination
    stop_reason: Optional[str] = None
    final_verdict: Optional[Verdict] = None

"""SQLite database engine, SQLAlchemy ORM records, and persistence mappers for RESQ Dev."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Optional, Tuple
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from resq.config import get_settings
from resq.models import (
    AgentDecision,
    AgentObservation,
    AgentStep,
    CandidatePatch,
    ExecutionResult,
    FailureArtifact,
    Verdict,
    VerificationJob,
    VerificationRun,
)

# Output bounding limits before persistence
MAX_STDOUT_CHARS = 65_536  # 64 KiB
MAX_STDERR_CHARS = 65_536  # 64 KiB
MAX_TRACEBACK_CHARS = 32_768  # 32 KiB
MAX_DIFF_CHARS = 65_536  # 64 KiB
MAX_RAW_RESPONSE_CHARS = 65_536  # 64 KiB

# SQLite signed 64-bit integer limits
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

Base = declarative_base()


def truncate_text(text: Optional[str], max_len: int, label: str = "output") -> Optional[str]:
    """Bounds text to max_len characters, appending a marker if truncated."""
    if text is None:
        return None
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n[... {label} truncated at {max_len} bytes ...]"


def serialize_failing_input(val: Any) -> Optional[str]:
    """Serializes failing_input to JSON.
    
    Preserves native JSON types (dicts, lists, scalars, strings, null).
    Explicitly handles non-JSON-serializable types using a structured diagnostic envelope.
    """
    if val is None:
        return None
    try:
        return json.dumps(val)
    except (TypeError, OverflowError):
        envelope = {
            "__unserializable__": True,
            "__type__": type(val).__name__,
            "__repr__": repr(val),
        }
        return json.dumps(envelope)


def deserialize_failing_input(raw: Optional[str]) -> Any:
    """Deserializes failing_input from JSON, preserving types and diagnostic envelopes."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return data
    except (json.JSONDecodeError, TypeError):
        return raw


def normalize_seed(seed: Optional[int]) -> Tuple[Optional[int], Optional[str], bool]:
    """Normalizes Hypothesis seeds for SQLite signed 64-bit integer storage.
    
    Preserves the original seed when within [-2^63, 2^63 - 1].
    If outside signed 64-bit range, maps it deterministically and records the transformation.
    
    Returns:
        (stored_int64_seed, original_seed_str, was_transformed)
    """
    if seed is None:
        return None, None, False

    original_str = str(seed)
    if INT64_MIN <= seed <= INT64_MAX:
        return seed, original_str, False

    # Deterministically fold into signed 64-bit integer space
    transformed = ((seed + (1 << 63)) % (1 << 64)) - (1 << 63)
    return transformed, original_str, True


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures a datetime instance is timezone-aware with UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class VerificationJobRecord(Base):
    """Database record for a verification job on a target module."""

    __tablename__ = "verification_jobs"

    id = Column(String(36), primary_key=True)
    target_filename = Column(String(255), nullable=False, default="target.py")
    test_filename = Column(String(255), nullable=False, default="test_target.py")
    source_code = Column(Text, nullable=False)
    invariants_code = Column(Text, nullable=False)
    current_status = Column(String(50), nullable=False, default="PENDING")
    final_verdict = Column(String(50), nullable=True)
    objective = Column(Text, nullable=True)
    execution_mode = Column(String(50), nullable=False, default="mock")
    termination_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    runs = relationship(
        "VerificationRunRecord",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="VerificationRunRecord.cycle_index",
    )

    agent_steps = relationship(
        "AgentStepRecord",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="AgentStepRecord.cycle_index",
    )


class AgentStepRecord(Base):
    """Database record for a single agent decision-observation cycle."""

    __tablename__ = "agent_steps"

    id = Column(String(36), primary_key=True)
    job_id = Column(
        String(36),
        ForeignKey("verification_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cycle_index = Column(Integer, nullable=False, default=0)
    action = Column(String(100), nullable=False)
    arguments = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    expected_observation = Column(Text, nullable=True)
    completion_status = Column(String(50), nullable=True, default="continue")
    success = Column(Boolean, default=True)
    output = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    evidence_payload = Column(Text, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("VerificationJobRecord", back_populates="agent_steps")



class VerificationRunRecord(Base):
    """Database record for an individual execution run in a job lifecycle."""

    __tablename__ = "verification_runs"

    id = Column(String(36), primary_key=True)
    job_id = Column(
        String(36),
        ForeignKey("verification_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_type = Column(String(50), nullable=False)
    cycle_index = Column(Integer, nullable=False, default=0)
    verdict = Column(String(50), nullable=False)
    unified_diff = Column(Text, nullable=True)

    # Execution result fields (bounded)
    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    timed_out = Column(Boolean, default=False)
    duration_seconds = Column(Float, default=0.0)

    # Failure artifact fields (bounded)
    minimized_input = Column(Text, nullable=True)
    exception_type = Column(String(255), nullable=True)
    assertion_message = Column(Text, nullable=True)
    traceback_raw = Column(Text, nullable=True)
    seed = Column(BigInteger, nullable=True)
    seed_original = Column(Text, nullable=True)
    seed_transformed = Column(Boolean, default=False)
    is_reproducible = Column(Boolean, default=False)

    # Candidate patch fields (bounded)
    patch_code = Column(Text, nullable=True)
    patch_explanation = Column(Text, nullable=True)
    patch_provider = Column(String(50), nullable=True)
    raw_model_response = Column(Text, nullable=True)

    executed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("VerificationJobRecord", back_populates="runs")


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Configures SQLite pragmas on every connection."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()


def get_engine(database_url: Optional[str] = None, echo: bool = False) -> Engine:
    """Creates a SQLAlchemy engine configured for RESQ Dev."""
    url = database_url or get_settings().database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, echo=echo, connect_args=connect_args)


def get_session_factory(engine: Optional[Engine] = None):
    """Returns a sessionmaker bound to the given or default engine."""
    eng = engine or get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=eng)


def init_db(engine: Optional[Engine] = None) -> None:
    """Creates all database tables and ensures schema is up to date."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)

    # Lightweight automatic schema migration for SQLite
    with eng.connect() as conn:
        try:
            # Check verification_jobs table columns
            res = conn.exec_driver_sql("PRAGMA table_info(verification_jobs)")
            existing_cols = {row[1] for row in res.fetchall()}
            if existing_cols:
                if "objective" not in existing_cols:
                    conn.exec_driver_sql("ALTER TABLE verification_jobs ADD COLUMN objective TEXT")
                if "execution_mode" not in existing_cols:
                    conn.exec_driver_sql("ALTER TABLE verification_jobs ADD COLUMN execution_mode VARCHAR(50) DEFAULT 'mock' NOT NULL")
                if "termination_reason" not in existing_cols:
                    conn.exec_driver_sql("ALTER TABLE verification_jobs ADD COLUMN termination_reason TEXT")
            conn.commit()
        except Exception:
            pass  # Non-SQLite or unmigratable engine



def startup_recovery(session) -> int:
    """Recovers interrupted jobs on server startup under the single-process model.
    
    Any job left in PENDING, RUNNING_BASELINE, or REPAIR_CYCLE_* was interrupted
    by an unclean process exit. It is transitioned to INTERRUPTED with final_verdict
    INFRASTRUCTURE_ERROR.
    
    Returns:
        Number of recovered jobs.
    """
    now = datetime.now(timezone.utc)
    active_statuses = [
        "PENDING",
        "RUNNING_BASELINE",
        "REPAIR_CYCLE_1",
        "REPAIR_CYCLE_2",
    ]
    records = (
        session.query(VerificationJobRecord)
        .filter(VerificationJobRecord.current_status.in_(active_statuses))
        .all()
    )
    count = 0
    for job in records:
        job.current_status = "INTERRUPTED"
        job.final_verdict = "INFRASTRUCTURE_ERROR"
        job.updated_at = now
        count += 1
    if count > 0:
        session.commit()
    return count


def domain_to_run_record(run: VerificationRun) -> VerificationRunRecord:
    """Converts a VerificationRun domain model into a bounded VerificationRunRecord."""
    rec = VerificationRunRecord(
        id=run.id,
        job_id=run.job_id,
        run_type=run.run_type,
        cycle_index=run.cycle_index,
        verdict=run.verdict.value if isinstance(run.verdict, Verdict) else str(run.verdict),
        unified_diff=truncate_text(run.unified_diff, MAX_DIFF_CHARS, "diff"),
        executed_at=ensure_utc(run.executed_at) or datetime.now(timezone.utc),
    )

    if run.execution_result:
        rec.exit_code = run.execution_result.exit_code
        rec.stdout = truncate_text(run.execution_result.stdout, MAX_STDOUT_CHARS, "stdout")
        rec.stderr = truncate_text(run.execution_result.stderr, MAX_STDERR_CHARS, "stderr")
        rec.timed_out = run.execution_result.timed_out
        rec.duration_seconds = run.execution_result.duration_seconds

    if run.failure_artifact:
        rec.minimized_input = serialize_failing_input(run.failure_artifact.failing_input)
        rec.exception_type = run.failure_artifact.exception_type
        rec.assertion_message = run.failure_artifact.assertion_message
        rec.traceback_raw = truncate_text(run.failure_artifact.traceback_raw, MAX_TRACEBACK_CHARS, "traceback")
        stored_seed, orig_seed_str, transformed = normalize_seed(run.failure_artifact.seed)
        rec.seed = stored_seed
        rec.seed_original = orig_seed_str
        rec.seed_transformed = transformed
        rec.is_reproducible = run.failure_artifact.is_reproducible

    if run.candidate_patch:
        rec.patch_code = run.candidate_patch.patch_code
        rec.patch_explanation = run.candidate_patch.explanation
        rec.patch_provider = run.candidate_patch.provider_name
        rec.raw_model_response = truncate_text(run.candidate_patch.raw_model_response, MAX_RAW_RESPONSE_CHARS, "raw_response")

    return rec


def run_record_to_domain(rec: VerificationRunRecord) -> VerificationRun:
    """Converts a VerificationRunRecord into a VerificationRun domain model."""
    exec_result = None
    if rec.exit_code is not None or rec.stdout or rec.stderr or rec.timed_out:
        exec_result = ExecutionResult(
            exit_code=rec.exit_code if rec.exit_code is not None else 0,
            stdout=rec.stdout or "",
            stderr=rec.stderr or "",
            timed_out=bool(rec.timed_out),
            duration_seconds=rec.duration_seconds or 0.0,
        )

    failure_art = None
    if rec.exception_type or rec.minimized_input or rec.traceback_raw or rec.seed is not None or rec.is_reproducible:
        failure_art = FailureArtifact(
            failing_input=deserialize_failing_input(rec.minimized_input),
            exception_type=rec.exception_type,
            assertion_message=rec.assertion_message,
            traceback_raw=rec.traceback_raw or "",
            seed=int(rec.seed_original) if rec.seed_original is not None else rec.seed,
            is_reproducible=bool(rec.is_reproducible),
        )

    cand_patch = None
    if rec.patch_code:
        cand_patch = CandidatePatch(
            patch_code=rec.patch_code,
            explanation=rec.patch_explanation or "",
            provider_name=rec.patch_provider or "mock",
            raw_model_response=rec.raw_model_response or "",
        )

    return VerificationRun(
        id=rec.id,
        job_id=rec.job_id,
        run_type=rec.run_type,
        cycle_index=rec.cycle_index,
        verdict=Verdict(rec.verdict),
        unified_diff=rec.unified_diff,
        execution_result=exec_result,
        failure_artifact=failure_art,
        candidate_patch=cand_patch,
        executed_at=ensure_utc(rec.executed_at) or datetime.now(timezone.utc),
    )


def domain_to_step_record(step: AgentStep) -> AgentStepRecord:
    """Converts an AgentStep domain model into a bounded AgentStepRecord."""
    args_json = json.dumps(step.decision.arguments) if step.decision.arguments else None
    evidence_json = json.dumps(step.observation.evidence_payload) if step.observation.evidence_payload else None

    return AgentStepRecord(
        id=step.id,
        cycle_index=step.cycle_index,
        action=step.decision.action,
        arguments=args_json,
        reason=truncate_text(step.decision.reason, 4096, "reason"),
        expected_observation=truncate_text(step.decision.expected_observation, 4096, "expected_observation"),
        completion_status=str(step.decision.completion_status),
        success=step.observation.success,
        output=truncate_text(str(step.observation.output) if step.observation.output is not None else None, MAX_STDOUT_CHARS, "output"),
        summary=truncate_text(step.observation.summary, 4096, "summary"),
        evidence_payload=evidence_json,
        duration_seconds=step.duration_seconds,
        created_at=ensure_utc(step.timestamp) or datetime.now(timezone.utc),
    )


def step_record_to_domain(rec: AgentStepRecord) -> AgentStep:
    """Converts an AgentStepRecord into an AgentStep domain model."""
    arguments = {}
    if rec.arguments:
        try:
            arguments = json.loads(rec.arguments)
        except Exception:
            arguments = {}

    evidence_payload = {}
    if rec.evidence_payload:
        try:
            evidence_payload = json.loads(rec.evidence_payload)
        except Exception:
            evidence_payload = {}

    decision = AgentDecision(
        action=rec.action,
        arguments=arguments,
        reason=rec.reason or "",
        expected_observation=rec.expected_observation or "",
        completion_status=rec.completion_status or "continue",
    )

    observation = AgentObservation(
        tool_name=rec.action,
        success=bool(rec.success),
        output=rec.output,
        summary=rec.summary or "",
        evidence_payload=evidence_payload,
    )

    return AgentStep(
        id=rec.id,
        cycle_index=rec.cycle_index,
        decision=decision,
        observation=observation,
        duration_seconds=rec.duration_seconds or 0.0,
        timestamp=ensure_utc(rec.created_at) or datetime.now(timezone.utc),
    )


def domain_to_job_record(job: VerificationJob, test_filename: str = "test_target.py") -> VerificationJobRecord:
    """Converts a VerificationJob domain model into a VerificationJobRecord."""
    rec = VerificationJobRecord(
        id=job.id,
        target_filename=job.target_filename,
        test_filename=test_filename,
        source_code=job.source_code,
        invariants_code=job.invariants_code,
        current_status=job.current_status,
        final_verdict=job.final_verdict.value if isinstance(job.final_verdict, Verdict) else job.final_verdict,
        objective=job.objective,
        execution_mode=job.execution_mode,
        termination_reason=job.termination_reason,
        created_at=ensure_utc(job.created_at) or datetime.now(timezone.utc),
        updated_at=ensure_utc(job.updated_at) or datetime.now(timezone.utc),
    )
    for run in job.runs:
        run_rec = domain_to_run_record(run)
        run_rec.job_id = job.id
        rec.runs.append(run_rec)

    for step in job.agent_steps:
        step_rec = domain_to_step_record(step)
        step_rec.job_id = job.id
        rec.agent_steps.append(step_rec)

    return rec


def job_record_to_domain(rec: VerificationJobRecord) -> VerificationJob:
    """Converts a VerificationJobRecord into a VerificationJob domain model."""
    domain_runs = [run_record_to_domain(r) for r in rec.runs]
    domain_steps = [step_record_to_domain(s) for s in getattr(rec, "agent_steps", [])]

    return VerificationJob(
        id=rec.id,
        target_filename=rec.target_filename,
        source_code=rec.source_code,
        invariants_code=rec.invariants_code,
        current_status=rec.current_status,
        final_verdict=Verdict(rec.final_verdict) if rec.final_verdict else None,
        objective=rec.objective or "Investigate failure, evaluate defect hypothesis, and verify candidate patch against edge-case invariants",
        execution_mode=rec.execution_mode or "mock",
        termination_reason=rec.termination_reason,
        runs=domain_runs,
        agent_steps=domain_steps,
        created_at=ensure_utc(rec.created_at) or datetime.now(timezone.utc),
        updated_at=ensure_utc(rec.updated_at) or datetime.now(timezone.utc),
    )


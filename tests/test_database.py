"""Unit tests for RESQ Dev SQLite database persistence, schema, and recovery."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import pytest
from sqlalchemy import inspect
from resq.database import (
    INT64_MAX,
    INT64_MIN,
    MAX_DIFF_CHARS,
    MAX_STDOUT_CHARS,
    VerificationJobRecord,
    VerificationRunRecord,
    deserialize_failing_input,
    domain_to_job_record,
    get_engine,
    get_session_factory,
    init_db,
    job_record_to_domain,
    normalize_seed,
    serialize_failing_input,
    startup_recovery,
    truncate_text,
)
from resq.models import (
    CandidatePatch,
    ExecutionResult,
    FailureArtifact,
    Verdict,
    VerificationJob,
    VerificationRun,
)


@pytest.fixture
def temp_db_path():
    """Provides a temporary SQLite database file path."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_resq.db"
        yield str(db_file)


@pytest.fixture
def db_session(temp_db_path):
    """Provides an active database session on a temporary SQLite database."""
    url = f"sqlite:///{temp_db_path}"
    engine = get_engine(url)
    init_db(engine)
    session_factory = get_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class TestDatabaseSchemaAndCRUD:
    """Validates table creation, constraints, foreign keys, and cascading deletes."""

    def test_table_creation(self, temp_db_path):
        url = f"sqlite:///{temp_db_path}"
        engine = get_engine(url)
        init_db(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "verification_jobs" in tables
        assert "verification_runs" in tables
        engine.dispose()

    def test_job_and_run_cascading_delete(self, db_session):
        # Create job with 2 runs
        job = VerificationJobRecord(
            id="job-1",
            target_filename="target.py",
            test_filename="test_target.py",
            source_code="def f(): pass",
            invariants_code="def test_f(): pass",
            current_status="PENDING",
        )
        run1 = VerificationRunRecord(
            id="run-1",
            job_id="job-1",
            run_type="BASELINE",
            cycle_index=0,
            verdict="REJECTED_STILL_FAILS",
        )
        run2 = VerificationRunRecord(
            id="run-2",
            job_id="job-1",
            run_type="REVERIFICATION",
            cycle_index=1,
            verdict="VERIFIED",
        )
        job.runs.extend([run1, run2])
        db_session.add(job)
        db_session.commit()

        # Verify records exist
        assert db_session.query(VerificationJobRecord).count() == 1
        assert db_session.query(VerificationRunRecord).count() == 2

        # Delete job -> runs must cascade delete
        db_session.delete(job)
        db_session.commit()

        assert db_session.query(VerificationJobRecord).count() == 0
        assert db_session.query(VerificationRunRecord).count() == 0


class TestPersistenceAcrossRestart:
    """Proves persistence survives complete engine disposal and reconnection."""

    def test_persistence_across_engine_recreation(self, temp_db_path):
        url = f"sqlite:///{temp_db_path}"

        # Session 1: Create engine, init, write records, close
        engine1 = get_engine(url)
        init_db(engine1)
        Session1 = get_session_factory(engine1)
        with Session1() as s1:
            job = VerificationJobRecord(
                id="persist-job-uuid",
                target_filename="math_lib.py",
                test_filename="test_math.py",
                source_code="def divide(a, b): return a / b",
                invariants_code="def test_div(): pass",
                current_status="COMPLETED",
                final_verdict="VERIFIED",
            )
            run = VerificationRunRecord(
                id="persist-run-uuid",
                job_id="persist-job-uuid",
                run_type="REVERIFICATION",
                cycle_index=1,
                verdict="VERIFIED",
                exit_code=0,
                stdout="1 passed in 0.05s",
                stderr="",
                timed_out=False,
                duration_seconds=0.05,
                patch_code="def divide(a, b): return a / b if b != 0 else None",
                unified_diff="--- target.py\n+++ target.py\n@@ ...",
            )
            job.runs.append(run)
            s1.add(job)
            s1.commit()

        engine1.dispose()

        # Session 2: Fresh engine pointing to same file
        engine2 = get_engine(url)
        Session2 = get_session_factory(engine2)
        with Session2() as s2:
            loaded_job = s2.query(VerificationJobRecord).filter_by(id="persist-job-uuid").first()
            assert loaded_job is not None
            assert loaded_job.target_filename == "math_lib.py"
            assert loaded_job.test_filename == "test_math.py"
            assert loaded_job.final_verdict == "VERIFIED"
            assert loaded_job.current_status == "COMPLETED"
            assert len(loaded_job.runs) == 1

            loaded_run = loaded_job.runs[0]
            assert loaded_run.id == "persist-run-uuid"
            assert loaded_run.verdict == "VERIFIED"
            assert loaded_run.exit_code == 0
            assert "1 passed" in loaded_run.stdout
            assert "--- target.py" in loaded_run.unified_diff

        engine2.dispose()


class TestFailingInputSerialization:
    """Verifies round-trip preservation of native JSON types and non-serializable objects."""

    def test_json_native_types_roundtrip(self):
        # Dictionaries
        d = {"arr": [1, 2, 3], "target": 2, "nested": {"k": "v"}}
        serialized = serialize_failing_input(d)
        restored = deserialize_failing_input(serialized)
        assert restored == d
        assert isinstance(restored, dict)
        assert isinstance(restored["arr"], list)

        # Lists
        lst = [0, -1, 42, "hello", True, None]
        assert deserialize_failing_input(serialize_failing_input(lst)) == lst

        # Scalars
        assert deserialize_failing_input(serialize_failing_input(0)) == 0
        assert deserialize_failing_input(serialize_failing_input(3.1415)) == 3.1415
        assert deserialize_failing_input(serialize_failing_input(True)) is True
        assert deserialize_failing_input(serialize_failing_input("some string")) == "some string"
        assert deserialize_failing_input(serialize_failing_input(None)) is None

    def test_unsupported_non_json_types_representation(self):
        # Set
        s = {1, 2, 3}
        serialized = serialize_failing_input(s)
        restored = deserialize_failing_input(serialized)
        assert isinstance(restored, dict)
        assert restored["__unserializable__"] is True
        assert restored["__type__"] == "set"
        assert "{1, 2, 3}" in restored["__repr__"] or "set" in restored["__repr__"]

        # Custom object
        class CustomInput:
            def __repr__(self):
                return "CustomInput(id=99)"

        obj = CustomInput()
        serialized_obj = serialize_failing_input(obj)
        restored_obj = deserialize_failing_input(serialized_obj)
        assert restored_obj["__unserializable__"] is True
        assert restored_obj["__type__"] == "CustomInput"
        assert restored_obj["__repr__"] == "CustomInput(id=99)"


class TestSeedNormalization:
    """Validates safe handling of Hypothesis seeds within SQLite signed 64-bit bounds."""

    def test_seed_none(self):
        stored, orig, transformed = normalize_seed(None)
        assert stored is None
        assert orig is None
        assert transformed is False

    def test_seed_standard_values(self):
        stored, orig, transformed = normalize_seed(42)
        assert stored == 42
        assert orig == "42"
        assert transformed is False

        # Signed 64-bit boundaries
        stored, orig, transformed = normalize_seed(INT64_MAX)
        assert stored == INT64_MAX
        assert orig == str(INT64_MAX)
        assert transformed is False

        stored, orig, transformed = normalize_seed(INT64_MIN)
        assert stored == INT64_MIN
        assert orig == str(INT64_MIN)
        assert transformed is False

    def test_seed_outside_signed_int64(self):
        # Hypothesis can produce unsigned 64-bit integers up to 2^64 - 1
        unsigned_large = (1 << 64) - 1
        stored, orig, transformed = normalize_seed(unsigned_large)
        assert transformed is True
        assert orig == str(unsigned_large)
        # Should be safely within SQLite signed 64-bit range
        assert INT64_MIN <= stored <= INT64_MAX


class TestOutputTruncation:
    """Verifies output strings are bounded to prevent database bloat."""

    def test_truncate_text(self):
        assert truncate_text(None, 100) is None
        assert truncate_text("short text", 100) == "short text"

        long_text = "A" * (MAX_STDOUT_CHARS + 500)
        truncated = truncate_text(long_text, MAX_STDOUT_CHARS, "stdout")
        assert len(truncated) > MAX_STDOUT_CHARS  # includes truncation message
        assert truncated.startswith("A" * MAX_STDOUT_CHARS)
        assert f"[... stdout truncated at {MAX_STDOUT_CHARS} bytes ...]" in truncated


class TestStartupRecovery:
    """Verifies unclean server restarts transition in-flight jobs to INTERRUPTED."""

    def test_startup_recovery_updates_only_active_jobs(self, db_session):
        # Active jobs that were in-flight when server died
        j_pending = VerificationJobRecord(
            id="job-pending",
            source_code="a",
            invariants_code="b",
            current_status="PENDING",
        )
        j_running = VerificationJobRecord(
            id="job-running",
            source_code="a",
            invariants_code="b",
            current_status="RUNNING_BASELINE",
        )
        j_repair1 = VerificationJobRecord(
            id="job-repair1",
            source_code="a",
            invariants_code="b",
            current_status="REPAIR_CYCLE_1",
        )

        # Terminal jobs that must NOT be modified
        j_completed = VerificationJobRecord(
            id="job-completed",
            source_code="a",
            invariants_code="b",
            current_status="COMPLETED",
            final_verdict="VERIFIED",
        )
        j_rejected = VerificationJobRecord(
            id="job-rejected",
            source_code="a",
            invariants_code="b",
            current_status="COMPLETED",
            final_verdict="REJECTED_STILL_FAILS",
        )
        j_failed = VerificationJobRecord(
            id="job-failed",
            source_code="a",
            invariants_code="b",
            current_status="FAILED",
            final_verdict="TIMEOUT_EXCEEDED",
        )

        db_session.add_all([j_pending, j_running, j_repair1, j_completed, j_rejected, j_failed])
        db_session.commit()

        # Run recovery
        recovered_count = startup_recovery(db_session)
        assert recovered_count == 3

        # Verify active jobs became INTERRUPTED with INFRASTRUCTURE_ERROR
        p = db_session.query(VerificationJobRecord).filter_by(id="job-pending").one()
        assert p.current_status == "INTERRUPTED"
        assert p.final_verdict == "INFRASTRUCTURE_ERROR"

        r = db_session.query(VerificationJobRecord).filter_by(id="job-running").one()
        assert r.current_status == "INTERRUPTED"
        assert r.final_verdict == "INFRASTRUCTURE_ERROR"

        c1 = db_session.query(VerificationJobRecord).filter_by(id="job-repair1").one()
        assert c1.current_status == "INTERRUPTED"
        assert c1.final_verdict == "INFRASTRUCTURE_ERROR"

        # Verify terminal jobs were untouched
        comp = db_session.query(VerificationJobRecord).filter_by(id="job-completed").one()
        assert comp.current_status == "COMPLETED"
        assert comp.final_verdict == "VERIFIED"

        rej = db_session.query(VerificationJobRecord).filter_by(id="job-rejected").one()
        assert rej.current_status == "COMPLETED"
        assert rej.final_verdict == "REJECTED_STILL_FAILS"

        fl = db_session.query(VerificationJobRecord).filter_by(id="job-failed").one()
        assert fl.current_status == "FAILED"
        assert fl.final_verdict == "TIMEOUT_EXCEEDED"


class TestDomainModelRoundtrip:
    """Verifies bidirectional conversion between Pydantic domain models and ORM records."""

    def test_full_domain_job_roundtrip(self, db_session):
        domain_job = VerificationJob(
            target_filename="binary_search.py",
            source_code="def bs(): pass",
            invariants_code="def test_bs(): pass",
            current_status="COMPLETED",
            final_verdict=Verdict.VERIFIED,
        )

        run1 = VerificationRun(
            job_id=domain_job.id,
            run_type="BASELINE",
            cycle_index=0,
            execution_result=ExecutionResult(
                exit_code=1,
                stdout="FAILED test_bs",
                stderr="",
                timed_out=False,
                duration_seconds=1.2,
            ),
            failure_artifact=FailureArtifact(
                failing_input={"arr": [0], "target": 0},
                exception_type="AssertionError",
                assertion_message="Expected 0 got -1",
                traceback_raw="Traceback ...",
                seed=9876543210987654321,  # Large 64-bit int
                is_reproducible=True,
            ),
            verdict=Verdict.REJECTED_STILL_FAILS,
        )

        run2 = VerificationRun(
            job_id=domain_job.id,
            run_type="REVERIFICATION",
            cycle_index=1,
            execution_result=ExecutionResult(
                exit_code=0,
                stdout="1 passed",
                stderr="",
                timed_out=False,
                duration_seconds=0.8,
            ),
            candidate_patch=CandidatePatch(
                patch_code="def bs(): return 0",
                explanation="Fixed return value",
                provider_name="mock",
                raw_model_response='{"patch": "..."}',
            ),
            unified_diff="--- a\n+++ b",
            verdict=Verdict.VERIFIED,
        )

        domain_job.runs.extend([run1, run2])

        # Convert to record and save
        job_record = domain_to_job_record(domain_job, test_filename="test_binary_search.py")
        db_session.add(job_record)
        db_session.commit()

        # Fetch and convert back to domain
        loaded_record = db_session.query(VerificationJobRecord).filter_by(id=domain_job.id).one()
        assert loaded_record.test_filename == "test_binary_search.py"
        restored_job = job_record_to_domain(loaded_record)

        assert restored_job.id == domain_job.id
        assert restored_job.target_filename == "binary_search.py"
        assert restored_job.current_status == "COMPLETED"
        assert restored_job.final_verdict == Verdict.VERIFIED
        assert len(restored_job.runs) == 2

        # Verify run 1
        r1 = restored_job.runs[0]
        assert r1.run_type == "BASELINE"
        assert r1.verdict == Verdict.REJECTED_STILL_FAILS
        assert r1.execution_result.exit_code == 1
        assert r1.failure_artifact.failing_input == {"arr": [0], "target": 0}
        assert r1.failure_artifact.exception_type == "AssertionError"
        assert r1.failure_artifact.seed == 9876543210987654321

        # Verify run 2
        r2 = restored_job.runs[1]
        assert r2.run_type == "REVERIFICATION"
        assert r2.verdict == Verdict.VERIFIED
        assert r2.execution_result.exit_code == 0
        assert r2.candidate_patch.patch_code == "def bs(): return 0"
        assert r2.unified_diff == "--- a\n+++ b"

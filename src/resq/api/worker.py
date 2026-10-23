"""Background worker executing verification jobs with short-lived database sessions."""

from typing import Optional
from resq.config import Settings, get_settings
from resq.database import (
    VerificationJobRecord,
    domain_to_run_record,
    get_session_factory,
)
from resq.engine.pipeline import VerificationPipeline
from resq.execution.docker_runner import DockerExecutionRunner
from resq.llm.factory import get_llm_provider
from resq.models import Verdict
from resq.api.schemas import JobStatus

NORMAL_COMPLETION_VERDICTS = {
    Verdict.VERIFIED,
    Verdict.NO_FAILURE_FOUND,
    Verdict.REJECTED_STILL_FAILS,
    Verdict.REJECTED_REGRESSION,
    Verdict.REJECTED_SYNTAX_ERROR,
    Verdict.INSUFFICIENT_EVIDENCE,
}


def run_verification_task(
    job_id: str,
    settings: Optional[Settings] = None,
    session_factory=None,
    pipeline: Optional[VerificationPipeline] = None,
) -> None:
    """Executes the verification pipeline in a background thread.
    
    Invariants:
    1. Short-Lived Sessions: Database transactions are NEVER held open while
       Docker containers or LLM network requests are running.
    2. Status vs Verdict: Clean rejections result in COMPLETED, not FAILED.
    3. Fatal Worker Safety: Uncaught worker crashes transition job to FAILED
       with INFRASTRUCTURE_ERROR. Interrupted work is never VERIFIED.
    """
    cfg = settings or get_settings()
    SessionLocal = session_factory or get_session_factory()

    # Session 1: Read job inputs and mark as RUNNING_BASELINE
    source_code: str = ""
    test_code: str = ""
    target_filename: str = "target.py"
    test_filename: str = "test_target.py"

    with SessionLocal() as session:
        job = session.query(VerificationJobRecord).filter_by(id=job_id).first()
        if not job:
            return  # Job was deleted or not found
        job.current_status = JobStatus.RUNNING_BASELINE.value
        source_code = job.source_code
        test_code = job.invariants_code
        target_filename = job.target_filename
        test_filename = job.test_filename
        session.commit()

    # [DATABASE IS CLOSED HERE - ZERO DB LOCKS DURING DOCKER/LLM EXECUTION]
    try:
        runner_pipeline = pipeline or VerificationPipeline(
            execution_env=DockerExecutionRunner(settings=cfg),
            llm_provider=get_llm_provider(cfg),
            settings=cfg,
        )

        completed_job = runner_pipeline.run(
            source_code=source_code,
            test_code=test_code,
            target_filename=target_filename,
            test_filename=test_filename,
        )

        # Session 2: Persist results and final status
        with SessionLocal() as session:
            job = session.query(VerificationJobRecord).filter_by(id=job_id).first()
            if not job:
                return

            # Append all runs from the pipeline run
            for domain_run in completed_job.runs:
                run_rec = domain_to_run_record(domain_run)
                run_rec.job_id = job.id
                job.runs.append(run_rec)

            final_verdict = completed_job.final_verdict
            job.final_verdict = final_verdict.value if final_verdict else None

            # Decouple Status from Verdict
            if final_verdict in NORMAL_COMPLETION_VERDICTS:
                job.current_status = JobStatus.COMPLETED.value
            else:
                job.current_status = JobStatus.FAILED.value

            session.commit()

    except Exception:
        # Emergency Session 3: Persist terminal failure on fatal worker crash
        try:
            with SessionLocal() as session:
                job = session.query(VerificationJobRecord).filter_by(id=job_id).first()
                if job:
                    job.current_status = JobStatus.FAILED.value
                    job.final_verdict = Verdict.INFRASTRUCTURE_ERROR.value
                    session.commit()
        except Exception:
            pass  # Suppress secondary DB errors

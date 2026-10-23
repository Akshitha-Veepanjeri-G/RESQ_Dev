"""API routes for RESQ Dev verification service."""

import subprocess
import uuid
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from resq.config import Settings
from resq.database import (
    VerificationJobRecord,
    deserialize_failing_input,
    ensure_utc,
    get_session_factory,
)
from resq.models import Verdict
from resq.api.schemas import (
    CandidatePatchResponse,
    ExecutionResultResponse,
    FailureArtifactResponse,
    HealthResponse,
    JobCreateRequest,
    JobDetailResponse,
    JobStatus,
    JobSummaryResponse,
    VerificationRunResponse,
)
from resq.api.worker import run_verification_task

router = APIRouter(prefix="/api/v1")


def get_db(request: Request):
    """Provides a short-lived database session from app state."""
    session_factory = getattr(request.app.state, "session_factory", None) or get_session_factory()
    with session_factory() as session:
        yield session


def get_app_settings(request: Request) -> Settings:
    """Retrieves settings from app state."""
    return getattr(request.app.state, "settings", None)


@router.get("/health", response_model=HealthResponse)
def health_check(request: Request):
    """Health check validating SQLite database and Docker daemon availability.
    
    Returns:
    - 200 OK (status="ok") when both DB and Docker are healthy.
    - 200 OK (status="degraded") when DB is healthy but Docker is unavailable.
    - 503 Service Unavailable (status="unhealthy") when DB is unreachable.
    """
    db_ok = False
    docker_ok = False

    # 1. Check SQLite connectivity
    try:
        session_factory = getattr(request.app.state, "session_factory", None) or get_session_factory()
        with session_factory() as session:
            session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    # 2. Check Docker daemon responsiveness
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=3,
        )
        docker_ok = res.returncode == 0
    except Exception:
        docker_ok = False

    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "database_connected": False,
                "docker_available": docker_ok,
                "version": "0.1.0",
            },
        )

    health_status = "ok" if docker_ok else "degraded"
    return HealthResponse(
        status=health_status,
        database_connected=True,
        docker_available=docker_ok,
        version="0.1.0",
    )


@router.post("/jobs", response_model=JobSummaryResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db=Depends(get_db),
):
    """Submits target Python source and test code for background verification."""
    job_id = str(uuid.uuid4())
    job_record = VerificationJobRecord(
        id=job_id,
        target_filename=payload.target_filename,
        test_filename=payload.test_filename,
        source_code=payload.source_code,
        invariants_code=payload.invariants_code,
        current_status=JobStatus.PENDING.value,
        final_verdict=None,
    )
    db.add(job_record)
    db.commit()

    # Schedule background execution worker
    settings = getattr(request.app.state, "settings", None)
    session_factory = getattr(request.app.state, "session_factory", None)
    pipeline_override = getattr(request.app.state, "pipeline", None)

    background_tasks.add_task(
        run_verification_task,
        job_id=job_id,
        settings=settings,
        session_factory=session_factory,
        pipeline=pipeline_override,
    )

    return JobSummaryResponse(
        job_id=job_id,
        target_filename=payload.target_filename,
        test_filename=payload.test_filename,
        current_status=JobStatus.PENDING,
        final_verdict=None,
        created_at=ensure_utc(job_record.created_at),
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job_detail(job_id: str, db=Depends(get_db)):
    """Retrieves full job status, runs, diffs, and verdicts.
    
    Submitted source_code and invariants_code are omitted by default.
    """
    job = db.query(VerificationJobRecord).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification job '{job_id}' not found",
        )

    run_responses: List[VerificationRunResponse] = []
    for r in job.runs:
        exec_resp = None
        if r.exit_code is not None or r.stdout or r.stderr or r.timed_out:
            exec_resp = ExecutionResultResponse(
                exit_code=r.exit_code if r.exit_code is not None else 0,
                stdout=r.stdout or "",
                stderr=r.stderr or "",
                timed_out=bool(r.timed_out),
                duration_seconds=r.duration_seconds or 0.0,
            )

        fail_resp = None
        if r.exception_type or r.minimized_input or r.traceback_raw or r.seed is not None or r.is_reproducible:
            fail_resp = FailureArtifactResponse(
                failing_input=deserialize_failing_input(r.minimized_input),
                exception_type=r.exception_type,
                assertion_message=r.assertion_message,
                traceback_raw=r.traceback_raw or "",
                seed=int(r.seed_original) if r.seed_original is not None else r.seed,
                is_reproducible=bool(r.is_reproducible),
            )

        patch_resp = None
        if r.patch_code:
            patch_resp = CandidatePatchResponse(
                patch_code=r.patch_code,
                explanation=r.patch_explanation or "",
                provider_name=r.patch_provider or "mock",
            )

        run_responses.append(
            VerificationRunResponse(
                id=r.id,
                job_id=r.job_id,
                run_type=r.run_type,
                cycle_index=r.cycle_index,
                verdict=Verdict(r.verdict),
                unified_diff=r.unified_diff,
                execution_result=exec_resp,
                failure_artifact=fail_resp,
                candidate_patch=patch_resp,
                executed_at=ensure_utc(r.executed_at),
            )
        )

    return JobDetailResponse(
        id=job.id,
        target_filename=job.target_filename,
        test_filename=job.test_filename,
        current_status=JobStatus(job.current_status),
        final_verdict=Verdict(job.final_verdict) if job.final_verdict else None,
        runs=run_responses,
        created_at=ensure_utc(job.created_at),
        updated_at=ensure_utc(job.updated_at),
    )


@router.get("/jobs", response_model=List[JobSummaryResponse])
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    """Returns a paginated list of recent verification jobs."""
    records = (
        db.query(VerificationJobRecord)
        .order_by(VerificationJobRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        JobSummaryResponse(
            job_id=rec.id,
            target_filename=rec.target_filename,
            test_filename=rec.test_filename,
            current_status=JobStatus(rec.current_status),
            final_verdict=Verdict(rec.final_verdict) if rec.final_verdict else None,
            created_at=ensure_utc(rec.created_at),
        )
        for rec in records
    ]

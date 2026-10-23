"""Integration and security tests for RESQ Dev FastAPI application."""

from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from resq.config import Settings
from resq.database import (
    VerificationJobRecord,
    get_engine,
    get_session_factory,
    init_db,
)
from resq.engine.pipeline import VerificationPipeline
from resq.execution.docker_runner import DockerExecutionRunner
from resq.llm.mock_provider import MockLLMProvider
from resq.models import (
    CandidatePatch,
    ExecutionResult,
    Verdict,
    VerificationJob,
    VerificationRun,
)
from resq.api.app import create_app
from resq.api.schemas import JobStatus

# Buggy fixture for end-to-end verification test
BUGGY_SOURCE = """def binary_search(arr: list[int], target: int) -> int:
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low < high:  # BUG
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
"""

CLEAN_PATCH = """def binary_search(arr: list[int], target: int) -> int:
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
"""

TEST_HARNESS = """from hypothesis import given, strategies as st
from target import binary_search

def test_baseline_empty():
    assert binary_search([], 5) == -1

@given(st.lists(st.integers(), unique=True).map(sorted), st.integers())
def test_hypothesis_finds_element(arr, target):
    idx = binary_search(arr, target)
    if target in arr:
        assert idx != -1
        assert arr[idx] == target
    else:
        assert idx == -1
"""


@pytest.fixture
def test_app_and_client():
    """Provides a TestClient with an isolated SQLite database."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_api.db"
        url = f"sqlite:///{db_path}"
        settings = Settings(
            database_url=url,
            llm_provider="mock",
            max_request_body_bytes=524_288,
        )
        engine = get_engine(url)
        init_db(engine)
        session_factory = get_session_factory(engine)
        app = create_app(settings=settings, session_factory=session_factory, engine=engine)
        with TestClient(app) as client:
            yield client, session_factory, settings


class TestHealthEndpoint:
    """Verifies the health check states."""

    def test_health_healthy(self, test_app_and_client):
        client, _, _ = test_app_and_client
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0)
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["database_connected"] is True
            assert data["docker_available"] is True

    def test_health_degraded_when_docker_down(self, test_app_and_client):
        client, _, _ = test_app_and_client
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=1)
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["database_connected"] is True
            assert data["docker_available"] is False

    def test_health_unhealthy_when_database_fails(self, test_app_and_client):
        client, _, _ = test_app_and_client
        with patch("resq.api.routes.get_session_factory") as mock_sf:
            mock_sf.side_effect = Exception("DB Connection refused")
            # Clear app state session factory
            client.app.state.session_factory = None
            resp = client.get("/api/v1/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["detail"]["status"] == "unhealthy"
            assert data["detail"]["database_connected"] is False


class TestRequestLimitsAndValidation:
    """Tests ASGI body limit, field limits, and strict filename validation."""

    def test_declared_body_size_limit_rejection(self, test_app_and_client):
        client, _, _ = test_app_and_client
        # Request claiming Content-Length > 512 KiB
        headers = {"Content-Length": "600000", "Content-Type": "application/json"}
        resp = client.post("/api/v1/jobs", content=b"{}", headers=headers)
        assert resp.status_code == 413
        assert "Request body exceeds maximum allowed size" in resp.json()["detail"]

    def test_source_code_field_limit(self, test_app_and_client):
        client, _, _ = test_app_and_client
        oversized_code = "x = 1\n" * 30_000  # > 128 KiB
        payload = {
            "source_code": oversized_code,
            "invariants_code": "def test(): pass",
            "target_filename": "target.py",
        }
        resp = client.post("/api/v1/jobs", json=payload)
        assert resp.status_code == 422

    def test_filename_validation_rules(self, test_app_and_client):
        client, _, _ = test_app_and_client
        base_payload = {
            "source_code": "def f(): pass",
            "invariants_code": "def test_f(): pass",
        }

        # Traversal rejection
        p1 = {**base_payload, "target_filename": "../escape.py"}
        assert client.post("/api/v1/jobs", json=p1).status_code == 422

        # Colon / Alternate Data Stream rejection
        p2 = {**base_payload, "target_filename": "target:ads.py"}
        assert client.post("/api/v1/jobs", json=p2).status_code == 422

        # Windows absolute path rejection
        p3 = {**base_payload, "target_filename": "C:\\Windows\\win.py"}
        assert client.post("/api/v1/jobs", json=p3).status_code == 422

        # Slash path separator rejection
        p4 = {**base_payload, "target_filename": "/etc/passwd.py"}
        assert client.post("/api/v1/jobs", json=p4).status_code == 422

        # Non-python extension rejection
        p5 = {**base_payload, "target_filename": "target.txt"}
        assert client.post("/api/v1/jobs", json=p5).status_code == 422

        # Valid basename accepted
        p6 = {**base_payload, "target_filename": "my_module.py", "test_filename": "test_my_module.py"}
        resp6 = client.post("/api/v1/jobs", json=p6)
        assert resp6.status_code == 202
        assert resp6.json()["target_filename"] == "my_module.py"
        assert resp6.json()["test_filename"] == "test_my_module.py"


class TestDataProtectionAndOmission:
    """Verifies that submitted source code is not exposed in default job responses."""

    def test_source_code_omitted_from_job_detail(self, test_app_and_client):
        client, session_factory, _ = test_app_and_client

        # Direct database insert
        with session_factory() as session:
            job = VerificationJobRecord(
                id="secret-job-uuid",
                target_filename="secret.py",
                test_filename="test_secret.py",
                source_code="SECRET_KEY = 'super_secret'",
                invariants_code="def test_secret(): pass",
                current_status="COMPLETED",
                final_verdict="VERIFIED",
            )
            session.add(job)
            session.commit()

        resp = client.get("/api/v1/jobs/secret-job-uuid")
        assert resp.status_code == 200
        data = resp.json()

        # Assert raw source and invariants code are omitted by default
        assert "source_code" not in data
        assert "invariants_code" not in data
        assert "SECRET_KEY" not in resp.text
        assert data["id"] == "secret-job-uuid"
        assert data["current_status"] == "COMPLETED"
        assert data["final_verdict"] == "VERIFIED"


class TestWorkerExceptionHandlingAndStatusSeparation:
    """Verifies fatal worker crash persistence and Status vs Verdict separation."""

    def test_worker_exception_persists_terminal_failure(self, test_app_and_client):
        client, session_factory, _ = test_app_and_client

        # Create mock pipeline that crashes with an unexpected unhandled exception
        mock_pipeline = MagicMock()
        mock_pipeline.run.side_effect = RuntimeError("Simulated unhandled worker crash")
        client.app.state.pipeline = mock_pipeline

        payload = {
            "source_code": "def f(): pass",
            "invariants_code": "def test_f(): pass",
            "target_filename": "target.py",
        }
        resp = client.post("/api/v1/jobs", json=payload)
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # Check detail: Worker exception must mark status FAILED and final_verdict INFRASTRUCTURE_ERROR
        detail_resp = client.get(f"/api/v1/jobs/{job_id}")
        assert detail_resp.status_code == 200
        job_data = detail_resp.json()
        assert job_data["current_status"] == "FAILED"
        assert job_data["final_verdict"] == "INFRASTRUCTURE_ERROR"

    def test_clean_rejection_results_in_completed_not_failed(self, test_app_and_client):
        client, session_factory, _ = test_app_and_client

        # Mock pipeline returning a normal rejection
        mock_pipeline = MagicMock()
        mock_job = VerificationJob(
            target_filename="target.py",
            source_code="def f(): pass",
            invariants_code="def test(): pass",
            current_status="COMPLETED",
            final_verdict=Verdict.REJECTED_STILL_FAILS,
        )
        mock_job.runs.append(
            VerificationRun(
                job_id=mock_job.id,
                run_type="REVERIFICATION",
                verdict=Verdict.REJECTED_STILL_FAILS,
            )
        )
        mock_pipeline.run.return_value = mock_job
        client.app.state.pipeline = mock_pipeline

        payload = {
            "source_code": "def f(): pass",
            "invariants_code": "def test(): pass",
        }
        resp = client.post("/api/v1/jobs", json=payload)
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        detail_resp = client.get(f"/api/v1/jobs/{job_id}")
        assert detail_resp.status_code == 200
        job_data = detail_resp.json()
        # Normal rejection must be COMPLETED, not FAILED
        assert job_data["current_status"] == "COMPLETED"
        assert job_data["final_verdict"] == "REJECTED_STILL_FAILS"


class TestJobEndpoints:
    """Tests 404s, list endpoints, and end-to-end verification."""

    def test_job_not_found(self, test_app_and_client):
        client, _, _ = test_app_and_client
        resp = client.get("/api/v1/jobs/non-existent-uuid")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_list_jobs_pagination(self, test_app_and_client):
        client, session_factory, _ = test_app_and_client
        with session_factory() as session:
            for i in range(5):
                session.add(
                    VerificationJobRecord(
                        id=f"job-{i}",
                        target_filename=f"target_{i}.py",
                        test_filename=f"test_target_{i}.py",
                        source_code="pass",
                        invariants_code="pass",
                        current_status="COMPLETED",
                        final_verdict="NO_FAILURE_FOUND",
                    )
                )
            session.commit()

        resp = client.get("/api/v1/jobs?limit=3&offset=0")
        assert resp.status_code == 200
        jobs = resp.json()
        assert len(jobs) == 3

    def test_e2e_verification_lifecycle_with_mock_provider(self, test_app_and_client):
        """Validates end-to-end verification lifecycle using MockLLMProvider and Docker."""
        client, session_factory, settings = test_app_and_client

        # Submit buggy code and property tests
        payload = {
            "source_code": BUGGY_SOURCE,
            "invariants_code": TEST_HARNESS,
            "target_filename": "target.py",
            "test_filename": "test_target.py",
        }
        submit_resp = client.post("/api/v1/jobs", json=payload)
        assert submit_resp.status_code == 202
        job_id = submit_resp.json()["job_id"]

        # In TestClient, BackgroundTasks run during request execution
        detail_resp = client.get(f"/api/v1/jobs/{job_id}")
        assert detail_resp.status_code == 200
        job_data = detail_resp.json()
        assert job_data["id"] == job_id
        assert job_data["current_status"] == "COMPLETED"
        assert job_data["final_verdict"] == "VERIFIED"
        assert len(job_data["runs"]) >= 2

        # Check baseline run
        baseline = job_data["runs"][0]
        assert baseline["run_type"] == "BASELINE"
        assert baseline["verdict"] == "REJECTED_STILL_FAILS"
        assert baseline["failure_artifact"] is not None
        assert baseline["failure_artifact"]["is_reproducible"] is True

        # Check reverification run
        reverify = job_data["runs"][1]
        assert reverify["run_type"] == "REVERIFICATION"
        assert reverify["verdict"] == "VERIFIED"
        assert reverify["unified_diff"] is not None
        assert reverify["execution_result"]["exit_code"] == 0

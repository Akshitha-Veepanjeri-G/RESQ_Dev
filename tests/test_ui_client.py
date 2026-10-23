"""Unit tests for RESQApiClient with mocked HTTP responses."""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, patch
import httpx
import pytest
from resq.models import Verdict
from resq.api.schemas import JobStatus
from resq.ui.api_client import (
    ApiClientError,
    ApiConnectionError,
    JobNotFoundError,
    RESQApiClient,
)


def mock_response(status_code: int, json_data: dict) -> httpx.Response:
    """Helper creating an httpx.Response with json body."""
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "http://127.0.0.1:8000/api/v1/test"),
    )


class TestRESQApiClientHealth:
    """Tests health endpoint handling in RESQApiClient."""

    def test_check_health_ok(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(
                200,
                {
                    "status": "ok",
                    "database_connected": True,
                    "docker_available": True,
                    "version": "0.1.0",
                },
            )
            health = client.check_health()
            assert health.status == "ok"
            assert health.database_connected is True
            assert health.docker_available is True
        client.close()

    def test_check_health_degraded(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(
                200,
                {
                    "status": "degraded",
                    "database_connected": True,
                    "docker_available": False,
                    "version": "0.1.0",
                },
            )
            health = client.check_health()
            assert health.status == "degraded"
            assert health.docker_available is False
        client.close()

    def test_check_health_unhealthy_503(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(
                503,
                {
                    "detail": {
                        "status": "unhealthy",
                        "database_connected": False,
                        "docker_available": True,
                        "version": "0.1.0",
                    }
                },
            )
            health = client.check_health()
            assert health.status == "unhealthy"
            assert health.database_connected is False
        client.close()

    def test_check_health_network_failure(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            health = client.check_health()
            assert health.status == "unhealthy"
            assert health.database_connected is False
            assert health.docker_available is False
        client.close()


class TestRESQApiClientJobSubmission:
    """Tests job submission and error handling."""

    def test_submit_job_success(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "post") as mock_post:
            mock_post.return_value = mock_response(
                202,
                {
                    "job_id": "job-1234",
                    "target_filename": "target.py",
                    "test_filename": "test_target.py",
                    "current_status": "PENDING",
                    "created_at": "2026-10-23T12:00:00Z",
                },
            )
            summary = client.submit_job(
                source_code="def f(): pass",
                invariants_code="def test_f(): pass",
            )
            assert summary.job_id == "job-1234"
            assert summary.current_status == JobStatus.PENDING
        client.close()

    def test_submit_job_413_payload_too_large(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "post") as mock_post:
            mock_post.return_value = mock_response(
                413,
                {"detail": "Request body exceeds maximum allowed size of 524288 bytes."},
            )
            with pytest.raises(ApiClientError) as exc_info:
                client.submit_job("x = 1", "def test(): pass")
            assert exc_info.value.status_code == 413
            assert "exceeds maximum allowed size" in exc_info.value.detail
        client.close()

    def test_submit_job_422_validation_error(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "post") as mock_post:
            mock_post.return_value = mock_response(
                422,
                {"detail": [{"loc": ["target_filename"], "msg": "Invalid filename"}]},
            )
            with pytest.raises(ApiClientError) as exc_info:
                client.submit_job("x = 1", "def test(): pass", target_filename="../bad.py")
            assert exc_info.value.status_code == 422
            assert "target_filename" in exc_info.value.detail
        client.close()

    def test_submit_job_connection_error(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Service offline")
            with pytest.raises(ApiConnectionError):
                client.submit_job("x = 1", "def test(): pass")
        client.close()


class TestRESQApiClientJobDetail:
    """Tests job retrieval and 404 handling."""

    def test_get_job_success(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(
                200,
                {
                    "id": "job-abc",
                    "target_filename": "target.py",
                    "test_filename": "test_target.py",
                    "current_status": "COMPLETED",
                    "final_verdict": "VERIFIED",
                    "runs": [],
                    "created_at": "2026-10-23T12:00:00Z",
                    "updated_at": "2026-10-23T12:00:05Z",
                },
            )
            detail = client.get_job("job-abc")
            assert detail.id == "job-abc"
            assert detail.current_status == JobStatus.COMPLETED
            assert detail.final_verdict == Verdict.VERIFIED
        client.close()

    def test_get_job_404_not_found(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(
                404,
                {"detail": "Verification job 'missing-uuid' not found"},
            )
            with pytest.raises(JobNotFoundError):
                client.get_job("missing-uuid")
        client.close()

    def test_get_job_malformed_response(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(200, {"unexpected": "data"})
            with pytest.raises(ApiClientError):
                client.get_job("job-abc")
        client.close()


class TestRESQApiClientListJobs:
    """Tests recent jobs listing."""

    def test_list_jobs_success(self):
        client = RESQApiClient(base_url="http://127.0.0.1:8000")
        with patch.object(client._client, "get") as mock_get:
            mock_get.return_value = mock_response(
                200,
                [
                    {
                        "job_id": "j-1",
                        "target_filename": "target.py",
                        "test_filename": "test_target.py",
                        "current_status": "COMPLETED",
                        "final_verdict": "VERIFIED",
                        "created_at": "2026-10-23T12:00:00Z",
                    }
                ],
            )
            jobs = client.list_jobs(limit=5)
            assert len(jobs) == 1
            assert jobs[0].job_id == "j-1"
        client.close()

    def test_client_context_manager(self):
        with RESQApiClient(base_url="http://127.0.0.1:8000") as client:
            assert client._client.is_closed is False
        assert client._client.is_closed is True

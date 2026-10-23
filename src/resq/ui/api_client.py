"""HTTP API client for communicating with the RESQ Dev FastAPI service."""

from typing import List, Optional
import httpx
from resq.api.schemas import (
    HealthResponse,
    JobCreateRequest,
    JobDetailResponse,
    JobSummaryResponse,
)


class ApiClientError(Exception):
    """Base exception for RESQ API client errors."""

    def __init__(self, detail: str, status_code: Optional[int] = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class ApiConnectionError(ApiClientError):
    """Raised when the backend API is unreachable or times out."""

    def __init__(self, detail: str = "Backend API is unreachable."):
        super().__init__(detail=detail, status_code=None)


class JobNotFoundError(ApiClientError):
    """Raised when a requested verification job is not found."""

    def __init__(self, job_id: str):
        super().__init__(detail=f"Verification job '{job_id}' not found.", status_code=404)


class RESQApiClient:
    """Synchronous HTTP client for Streamlit frontend calling RESQ Dev API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 10.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._owned_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        """Closes the underlying HTTP client if owned."""
        if self._owned_client and not self._client.is_closed:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _extract_detail(self, resp: httpx.Response, default: str) -> str:
        """Safely extracts detail string from JSON error response."""
        try:
            data = resp.json()
            if isinstance(data, dict):
                detail = data.get("detail", default)
                if isinstance(detail, list):
                    # Pydantic validation error list
                    return "; ".join(f"{e.get('loc', [''])[0]}: {e.get('msg', '')}" for e in detail if isinstance(e, dict))
                return str(detail)
            return default
        except Exception:
            return default

    def check_health(self) -> HealthResponse:
        """Queries the /health endpoint and returns a HealthResponse.
        
        Returns a synthetic degraded or unhealthy HealthResponse if connection fails,
        ensuring the UI can render actionable status without crashing.
        """
        try:
            resp = self._client.get("/api/v1/health")
            if resp.status_code == 200:
                data = resp.json()
                return HealthResponse.model_validate(data)
            elif resp.status_code == 503:
                try:
                    data = resp.json()
                    detail = data.get("detail", {}) if isinstance(data, dict) else {}
                    return HealthResponse(
                        status="unhealthy",
                        database_connected=bool(detail.get("database_connected", False)),
                        docker_available=bool(detail.get("docker_available", False)),
                        version=str(detail.get("version", "0.1.0")),
                    )
                except Exception:
                    return HealthResponse(status="unhealthy", database_connected=False, docker_available=False)
            return HealthResponse(status="unhealthy", database_connected=False, docker_available=False)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
            return HealthResponse(status="unhealthy", database_connected=False, docker_available=False)
        except Exception:
            return HealthResponse(status="unhealthy", database_connected=False, docker_available=False)

    def submit_job(
        self,
        source_code: str,
        invariants_code: str,
        target_filename: str = "target.py",
        test_filename: str = "test_target.py",
    ) -> JobSummaryResponse:
        """Submits a verification job to POST /api/v1/jobs."""
        try:
            payload = JobCreateRequest(
                source_code=source_code,
                invariants_code=invariants_code,
                target_filename=target_filename,
                test_filename=test_filename,
            )
            payload_dict = payload.model_dump()
        except Exception as exc:
            raise ApiClientError(f"Client payload validation failed: {exc}", status_code=422) from exc

        try:
            resp = self._client.post("/api/v1/jobs", json=payload_dict)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ApiConnectionError(f"Failed to connect to API at {self.base_url}: {exc}") from exc

        if resp.status_code == 202:
            try:
                return JobSummaryResponse.model_validate(resp.json())
            except Exception as exc:
                raise ApiClientError(f"Malformed response from API: {exc}", status_code=resp.status_code) from exc
        elif resp.status_code == 413:
            detail = self._extract_detail(resp, "Request body exceeds maximum size limit (512 KiB).")
            raise ApiClientError(detail, status_code=413)
        elif resp.status_code in (400, 422):
            detail = self._extract_detail(resp, "Invalid request payload.")
            raise ApiClientError(detail, status_code=resp.status_code)
        else:
            detail = self._extract_detail(resp, f"API returned status {resp.status_code}")
            raise ApiClientError(detail, status_code=resp.status_code)

    def get_job(self, job_id: str) -> JobDetailResponse:
        """Fetches full job verification details from GET /api/v1/jobs/{job_id}."""
        try:
            resp = self._client.get(f"/api/v1/jobs/{job_id}")
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ApiConnectionError(f"Failed to connect to API at {self.base_url}: {exc}") from exc

        if resp.status_code == 200:
            try:
                return JobDetailResponse.model_validate(resp.json())
            except Exception as exc:
                raise ApiClientError(f"Malformed job detail response: {exc}", status_code=resp.status_code) from exc
        elif resp.status_code == 404:
            raise JobNotFoundError(job_id)
        elif resp.status_code == 422:
            detail = self._extract_detail(resp, f"Invalid job ID: '{job_id}'.")
            raise ApiClientError(detail, status_code=422)
        else:
            detail = self._extract_detail(resp, f"API returned status {resp.status_code}")
            raise ApiClientError(detail, status_code=resp.status_code)

    def list_jobs(self, limit: int = 20, offset: int = 0) -> List[JobSummaryResponse]:
        """Fetches recent verification jobs from GET /api/v1/jobs."""
        try:
            resp = self._client.get("/api/v1/jobs", params={"limit": limit, "offset": offset})
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ApiConnectionError(f"Failed to connect to API at {self.base_url}: {exc}") from exc

        if resp.status_code == 200:
            try:
                raw_list = resp.json()
                if not isinstance(raw_list, list):
                    raise ApiClientError("Expected a list of jobs from API.", status_code=200)
                return [JobSummaryResponse.model_validate(item) for item in raw_list]
            except Exception as exc:
                raise ApiClientError(f"Malformed job list response: {exc}", status_code=resp.status_code) from exc
        else:
            detail = self._extract_detail(resp, f"API returned status {resp.status_code}")
            raise ApiClientError(detail, status_code=resp.status_code)

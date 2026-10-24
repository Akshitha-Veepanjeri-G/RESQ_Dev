"""Tests validating provider selection policy, credential enforcement, and no-silent-fallback guarantees."""

import os
import pytest
from unittest.mock import patch

from resq.config import Settings
from resq.llm.factory import get_llm_provider
from resq.llm.mock_provider import MockLLMProvider
from resq.llm.gemini_provider import GeminiLLMProvider
from resq.models import Verdict
from resq.api.schemas import JobStatus
from resq.api.worker import run_verification_task
from resq.database import (
    VerificationJobRecord,
    get_engine,
    get_session_factory,
    init_db,
)


class TestProviderSelectionPolicy:
    """Proves that Gemini-configured jobs cannot silently fall back to mock provider."""

    def test_mock_provider_selected_by_default(self):
        settings = Settings(llm_provider="mock")
        provider = get_llm_provider(settings)
        assert isinstance(provider, MockLLMProvider)
        assert provider.provider_name == "mock"

    def test_gemini_requested_without_key_raises_explicit_error(self):
        """When Gemini is requested without credentials, factory must raise explicit ValueError."""
        settings = Settings(llm_provider="gemini", gemini_api_key=None)
        with pytest.raises(ValueError, match="Silent fallback to mock provider is strictly forbidden"):
            get_llm_provider(settings)

    def test_gemini_requested_with_key_returns_gemini_provider(self):
        settings = Settings(llm_provider="gemini", gemini_api_key="fake-test-key")
        provider = get_llm_provider(settings)
        assert isinstance(provider, GeminiLLMProvider)
        assert provider.provider_name == "gemini"

    def test_resq_env_prefix_properly_recognized(self):
        """Validates that RESQ_LLM_PROVIDER and RESQ_GEMINI_API_KEY env vars are read."""
        with patch.dict(os.environ, {
            "RESQ_LLM_PROVIDER": "gemini",
            "RESQ_GEMINI_API_KEY": "resq-prefix-key",
            "RESQ_GEMINI_MODEL": "gemini-test-model",
        }):
            settings = Settings()
            assert settings.llm_provider == "gemini"
            assert settings.gemini_api_key == "resq-prefix-key"
            assert settings.gemini_model == "gemini-test-model"

    def test_worker_fails_explicitly_when_gemini_has_no_credentials(self, tmp_path):
        """Worker must mark job as FAILED with LLM_ERROR when Gemini provider is misconfigured."""
        db_path = tmp_path / "test_worker_policy.db"
        engine = get_engine(f"sqlite:///{db_path}")
        init_db(engine)
        session_factory = get_session_factory(engine)

        with session_factory() as session:
            job = VerificationJobRecord(
                id="job-policy-fail",
                target_filename="target.py",
                test_filename="test_target.py",
                source_code="def fn(): pass",
                invariants_code="def test_fn(): pass",
                current_status="PENDING",
            )
            session.add(job)
            session.commit()

        # Settings with Gemini requested but no API key
        settings = Settings(
            database_url=f"sqlite:///{db_path}",
            llm_provider="gemini",
            gemini_api_key=None,
        )

        run_verification_task(
            job_id="job-policy-fail",
            settings=settings,
            session_factory=session_factory,
        )

        with session_factory() as session:
            record = session.query(VerificationJobRecord).filter_by(id="job-policy-fail").first()
            assert record is not None
            assert record.current_status == JobStatus.FAILED.value
            assert record.final_verdict == Verdict.LLM_ERROR.value
            assert record.execution_mode == "live_gemini"
            assert "Silent fallback to mock provider is strictly forbidden" in (record.termination_reason or "")

        engine.dispose()

    def test_dotenv_loading_and_env_var_override(self, tmp_path):
        """Validates that .env loads properly and system environment variables override .env."""
        dotenv_file = tmp_path / ".env"
        dotenv_file.write_text(
            "RESQ_LLM_PROVIDER=gemini\nGEMINI_API_KEY=key-from-dotenv\nRESQ_GEMINI_MODEL=gemini-2.5-flash\n",
            encoding="utf-8",
        )

        # 1. Load from .env file directly
        settings_from_dotenv = Settings(_env_file=str(dotenv_file))
        assert settings_from_dotenv.llm_provider == "gemini"
        assert settings_from_dotenv.gemini_api_key == "key-from-dotenv"

        # 2. System environment variable takes precedence over .env file
        with patch.dict(os.environ, {"GEMINI_API_KEY": "key-from-system-override"}):
            settings_with_override = Settings(_env_file=str(dotenv_file))
            assert settings_with_override.gemini_api_key == "key-from-system-override"

    def test_api_submitting_job_without_gemini_credentials_rejected(self, tmp_path):
        """API must reject job creation with HTTP 400 when Gemini provider lacks credentials."""
        from fastapi.testclient import TestClient
        from resq.api.app import create_app

        db_path = tmp_path / "test_api_rejection.db"
        engine = get_engine(f"sqlite:///{db_path}")
        init_db(engine)
        session_factory = get_session_factory(engine)

        settings = Settings(
            database_url=f"sqlite:///{db_path}",
            llm_provider="gemini",
            gemini_api_key=None,
        )
        app = create_app(settings=settings, session_factory=session_factory, engine=engine)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/jobs",
                json={
                    "target_filename": "target.py",
                    "test_filename": "test_target.py",
                    "source_code": "def f(): pass",
                    "invariants_code": "def test_f(): pass",
                },
            )
            assert resp.status_code == 400
            detail = resp.json()["detail"]
            assert "Gemini LLM provider is configured" in detail
            assert "Silent fallback to mock mode is disabled" in detail

            # Health endpoint returns safe indicator
            health_resp = client.get("/api/v1/health")
            assert health_resp.status_code == 200
            health_data = health_resp.json()
            assert health_data["llm_provider"] == "gemini"
            assert health_data["credential_configured"] is False

        engine.dispose()


"""Deterministic offline unit tests for GeminiLLMProvider and provider factory."""

from unittest.mock import MagicMock
import pytest
from resq.config import Settings
from resq.llm.base import LLMProvider
from resq.llm.exceptions import LLMProviderError
from resq.llm.factory import get_llm_provider
from resq.llm.gemini_provider import GeminiLLMProvider, StructuredPatchResponse
from resq.llm.mock_provider import MockLLMProvider
from resq.models import FailureArtifact


@pytest.fixture
def sample_failure() -> FailureArtifact:
    return FailureArtifact(
        exception_type="AssertionError",
        assertion_message="Failed to find 0 in [0]",
        failing_input="arr=[0]",
        traceback_raw="AssertionError: Failed to find 0 in [0]\n  assert -1 != -1",
        seed=12345,
        is_reproducible=True,
    )


class TestProviderFactory:
    """Verifies provider factory selection and default offline behavior."""

    def test_default_provider_is_mock(self):
        """Ensures default settings resolve to MockLLMProvider without network or credentials."""
        provider = get_llm_provider()
        assert isinstance(provider, MockLLMProvider)
        assert isinstance(provider, LLMProvider)

    def test_explicit_mock_provider_selection(self):
        settings = Settings(llm_provider="mock")
        provider = get_llm_provider(settings)
        assert isinstance(provider, MockLLMProvider)

    def test_gemini_provider_selection(self):
        settings = Settings(llm_provider="gemini", gemini_api_key="mock_test_key")
        provider = get_llm_provider(settings)
        assert isinstance(provider, GeminiLLMProvider)

    def test_unsupported_provider_raises_value_error(self):
        settings = Settings(llm_provider="unsupported_vendor")
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm_provider(settings)


class TestGeminiLLMProvider:
    """Tests GeminiLLMProvider behavior, timeout handling, error mapping, and safety."""

    def test_missing_api_key_raises_error(self, sample_failure):
        """Verifies that missing credentials abort before network attempts."""
        settings = Settings(llm_provider="gemini", gemini_api_key=None)
        provider = GeminiLLMProvider(settings=settings)
        with pytest.raises(LLMProviderError, match="Gemini API key is not configured"):
            provider.generate_patch("def test(): pass", sample_failure)

    def test_successful_structured_patch_generation(self, sample_failure):
        """Verifies candidate patch generation with mocked GenAI client."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
            gemini_model="gemini-2.5-flash",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = '{"explanation": "Corrected off-by-one boundary.", "patch_code": "def binary_search():\\n    return 0\\n"}'
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        patch = provider.generate_patch("def binary_search(): return -1", sample_failure)

        assert patch.provider_name == "gemini"
        assert patch.explanation == "Corrected off-by-one boundary."
        assert "def binary_search():" in patch.patch_code
        assert mock_client.models.generate_content.called

    def test_successful_parsed_response_attribute(self, sample_failure):
        """Verifies handling when SDK directly returns a pre-parsed response."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = StructuredPatchResponse(
            explanation="SDK pre-parsed fix.",
            patch_code="def fixed_func(): return True\n",
        )
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        patch = provider.generate_patch("def fixed_func(): return False", sample_failure)

        assert patch.explanation == "SDK pre-parsed fix."
        assert "def fixed_func(): return True" in patch.patch_code

    def test_markdown_code_fence_stripping(self, sample_failure):
        """Verifies that markdown fences enclosing JSON are properly stripped."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = '```json\n{"explanation": "Fenced fix.", "patch_code": "x = 42\\n"}\n```'
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        patch = provider.generate_patch("x = 0", sample_failure)

        assert patch.explanation == "Fenced fix."
        assert patch.patch_code == "x = 42\n"

    def test_timeout_error_mapping(self, sample_failure):
        """Verifies that API request timeouts are mapped to LLMProviderError without crash."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
            llm_request_timeout_seconds=5.0,
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = TimeoutError("Network read deadline expired")

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate_patch("x = 1", sample_failure)

        assert "timed out" in str(exc_info.value).lower()

    def test_rate_limit_error_mapping(self, sample_failure):
        """Verifies that HTTP 429 quota errors are mapped with status_code 429."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 ResourceExhausted: Quota limit reached")

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate_patch("x = 1", sample_failure)

        assert exc_info.value.status_code == 429
        assert "rate limit" in str(exc_info.value).lower() or "quota" in str(exc_info.value).lower()

    def test_auth_error_mapping_does_not_leak_key(self, sample_failure):
        """Verifies that HTTP 401/403 authentication failures do not log or leak the raw API key."""
        secret_key = "super_secret_api_key_abc_xyz"
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key=secret_key,
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("401 Unauthenticated: Invalid API key credentials")

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate_patch("x = 1", sample_failure)

        assert exc_info.value.status_code == 401
        assert "authentication failed" in str(exc_info.value).lower()
        # Verify secret key is not in exception message
        assert secret_key not in str(exc_info.value)

    def test_generic_exception_does_not_leak_key(self, sample_failure):
        """Regression test: verifies arbitrary generic exceptions containing the API key cannot leak it."""
        secret_key = "AIzaSyFakeSecretKey9876543210"
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key=secret_key,
        )

        mock_client = MagicMock()
        # Simulate generic HTTP / transport error embedding the secret key in the error string
        mock_client.models.generate_content.side_effect = RuntimeError(
            f"Failed connection to https://generativelanguage.googleapis.com/v1beta?key={secret_key}"
        )

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate_patch("x = 1", sample_failure)

        assert secret_key not in str(exc_info.value)
        assert "unexpected provider error" in str(exc_info.value).lower()

    def test_malformed_json_response_rejected(self, sample_failure):
        """Verifies that non-JSON model output is cleanly rejected."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = "I think you should fix the code by doing x = y."
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError, match="Failed to parse structured patch"):
            provider.generate_patch("x = 1", sample_failure)

    def test_empty_patch_code_rejected(self, sample_failure):
        """Verifies that empty candidate patch code is rejected."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = '{"explanation": "Did not write code", "patch_code": "   "}'
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError, match="empty patch code"):
            provider.generate_patch("x = 1", sample_failure)

    def test_empty_response_body_rejected(self, sample_failure):
        """Verifies that an empty response body is rejected."""
        settings = Settings(
            llm_provider="gemini",
            gemini_api_key="mock_secret_key_123",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiLLMProvider(settings=settings, client=mock_client)
        with pytest.raises(LLMProviderError, match="empty response body"):
            provider.generate_patch("x = 1", sample_failure)

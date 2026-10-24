"""Provider factory for instantiating configured LLM adapters."""

from typing import Optional
from resq.config import Settings, get_settings
from resq.llm.base import LLMProvider
from resq.llm.mock_provider import MockLLMProvider


def get_llm_provider(settings: Optional[Settings] = None) -> LLMProvider:
    """Instantiates and returns the configured LLMProvider implementation.

    Defaults to MockLLMProvider to guarantee offline, deterministic testing.
    GeminiLLMProvider is selected only when explicitly configured via settings or environment.

    Args:
        settings: Optional Settings instance. Defaults to get_settings().

    Returns:
        Configured LLMProvider instance.

    Raises:
        ValueError: If configured provider name is unknown.
    """
    active_settings = settings or get_settings()
    provider_name = (active_settings.llm_provider or "mock").lower().strip()

    if provider_name == "mock":
        return MockLLMProvider()

    if provider_name == "gemini":
        if not active_settings.gemini_api_key:
            raise ValueError(
                "Gemini LLM provider requested (RESQ_LLM_PROVIDER=gemini), but no API key was configured. "
                "Set GEMINI_API_KEY or RESQ_GEMINI_API_KEY in the environment or .env file. "
                "Silent fallback to mock provider is strictly forbidden."
            )
        from resq.llm.gemini_provider import GeminiLLMProvider
        return GeminiLLMProvider(settings=active_settings)

    raise ValueError(
        f"Unsupported LLM provider: '{provider_name}'. "
        "Supported providers: 'mock', 'gemini'."
    )

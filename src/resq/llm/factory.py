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
        from resq.llm.gemini_provider import GeminiLLMProvider
        return GeminiLLMProvider(settings=active_settings)

    raise ValueError(
        f"Unsupported LLM provider: '{provider_name}'. "
        "Supported providers: 'mock', 'gemini'."
    )

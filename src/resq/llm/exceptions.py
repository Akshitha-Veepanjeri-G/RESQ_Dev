"""Custom exceptions for RESQ Dev LLM providers."""


class LLMProviderError(Exception):
    """Base exception for external LLM provider failures.

    Includes missing credentials, authentication failures, API rate limits,
    HTTP timeouts, network failures, and malformed responses.
    """

    def __init__(self, message: str, provider_name: str = "llm", status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.status_code = status_code

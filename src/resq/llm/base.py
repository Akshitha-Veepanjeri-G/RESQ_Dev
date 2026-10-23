"""Abstract interface for replaceable LLM providers."""

from abc import ABC, abstractmethod
from resq.models import CandidatePatch, FailureArtifact


class LLMProvider(ABC):
    """Abstract interface for proposing candidate code patches based on failure evidence."""

    @abstractmethod
    def generate_patch(self, source_code: str, failure: FailureArtifact) -> CandidatePatch:
        """Synthesizes a candidate patch given the source code and failure evidence.

        Args:
            source_code: The original user source code under verification.
            failure: Structured failure artifact containing traceback, input, and exception.

        Returns:
            CandidatePatch containing proposed code and explanation.
        """
        pass

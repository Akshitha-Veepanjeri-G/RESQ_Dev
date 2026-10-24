"""Abstract interface for replaceable LLM providers."""

from abc import ABC, abstractmethod
from typing import Any
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

    def decide_action(self, state: Any) -> Any:
        """Evaluates current verification state and selects next bounded verification action.

        Args:
            state: AgentState snapshot.

        Returns:
            AgentDecision with selected tool, arguments, and evidence-based rationale.
        """
        raise NotImplementedError("decide_action is not implemented by this LLM provider.")


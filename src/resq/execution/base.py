"""Abstract execution environment contract for running code in isolation."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from resq.models import ExecutionResult


class InfrastructureError(RuntimeError):
    """Raised when execution infrastructure (Docker daemon, container runtime, host isolation) fails."""
    pass


class ExecutionEnvironment(ABC):
    """Abstract interface for isolated test execution."""

    @abstractmethod
    def execute(
        self,
        workspace_path: Path,
        command: list[str],
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        """Executes a command inside the isolated environment.

        Args:
            workspace_path: Path to the isolated directory to mount as the workspace.
            command: The command line arguments to execute.
            timeout_seconds: Hard execution deadline in seconds.

        Returns:
            ExecutionResult with exit_code, stdout, stderr, timed_out, duration_seconds.
        """
        pass

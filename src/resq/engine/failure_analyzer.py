"""Parses pytest and Hypothesis test outputs to extract structured failure evidence."""

import re
from typing import Any, Optional
from resq.models import ExecutionResult, FailureArtifact


class FailureAnalyzer:
    """Extracts falsifying examples, tracebacks, exception types, and random seeds from test outputs."""

    FALSIFYING_EXAMPLE_PATTERN = re.compile(
        r"(?:^E\s+)?(?:Falsifying example|Failing test case):\s*(?:[a-zA-Z0-9_.]+\()?\s*\n?((?:(?!\n(?:E\s+)?[A-Z]|\n\S|Explanation:).)+)",
        re.MULTILINE | re.DOTALL,
    )
    SEED_PATTERN = re.compile(
        r"(?:--hypothesis-seed=|@?seed[=:\s\(]+)(\d+)",
        re.IGNORECASE,
    )
    EXCEPTION_PATTERN = re.compile(
        r"^E\s+([a-zA-Z0-9_]*(?:Error|Exception))(?::\s*(.*))?$",
        re.MULTILINE,
    )
    FAILED_TEST_HEADER_PATTERN = re.compile(
        r"_{3,}\s+([a-zA-Z0-9_]+)\s+_{3,}",
        re.MULTILINE,
    )

    def analyze(self, result: ExecutionResult) -> FailureArtifact:
        """Analyzes an ExecutionResult to extract a FailureArtifact.

        Args:
            result: The ExecutionResult from running pytest in the sandbox.

        Returns:
            A FailureArtifact with parsed evidence.
        """
        combined_output = f"{result.stdout}\n{result.stderr}".strip()

        # Handle timeout case
        if result.timed_out or result.exit_code == 124:
            return FailureArtifact(
                assertion_message="Execution timed out.",
                traceback_raw=combined_output,
                is_reproducible=False,
            )

        # Handle zero exit code (no failure)
        if result.exit_code == 0:
            return FailureArtifact(
                traceback_raw=combined_output,
                is_reproducible=False,
            )

        # 1. Extract Hypothesis falsifying example / failing test case
        failing_input: Optional[Any] = None
        falsifying_match = self.FALSIFYING_EXAMPLE_PATTERN.search(combined_output)
        if falsifying_match:
            raw_input_str = falsifying_match.group(1).strip()
            # Clean leading E and whitespace on each line if present
            cleaned_lines = [re.sub(r"^E\s*", "", line).strip() for line in raw_input_str.splitlines()]
            cleaned_input = " ".join(cleaned_lines).rstrip(")").rstrip(",").strip()
            if cleaned_input:
                failing_input = cleaned_input

        # 2. Extract Hypothesis seed
        seed: Optional[int] = None
        seed_match = self.SEED_PATTERN.search(combined_output)
        if seed_match:
            try:
                seed = int(seed_match.group(1))
            except ValueError:
                seed = None

        # 3. Extract exception type and assertion message
        exception_type: Optional[str] = None
        assertion_message: Optional[str] = None
        exc_match = self.EXCEPTION_PATTERN.search(combined_output)
        if exc_match:
            exception_type = exc_match.group(1).strip()
            assertion_message = (exc_match.group(2) or "").strip()
        else:
            assert_match = re.search(r"^E\s+(assert\s+.*)$", combined_output, re.MULTILINE)
            if assert_match:
                exception_type = "AssertionError"
                assertion_message = assert_match.group(1).strip()

        # 4. Extract traceback snippet
        traceback_raw = combined_output
        if "Traceback" in combined_output or "___ " in combined_output:
            # Capture from test failure header onwards
            header_match = self.FAILED_TEST_HEADER_PATTERN.search(combined_output)
            if header_match:
                traceback_raw = combined_output[header_match.start():]

        # Determine if sufficient evidence was found to be reproducible
        is_reproducible = bool(failing_input or (exception_type and assertion_message))

        return FailureArtifact(
            failing_input=failing_input,
            exception_type=exception_type,
            assertion_message=assertion_message,
            traceback_raw=traceback_raw,
            seed=seed,
            is_reproducible=is_reproducible,
        )

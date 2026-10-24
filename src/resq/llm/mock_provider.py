"""Deterministic mock LLM provider for zero-cost offline testing of the verification loop."""

from typing import Optional
from resq.llm.base import LLMProvider
from resq.models import CandidatePatch, FailureArtifact

# Verified patch for benchmark 01 (binary search off-by-one fix)
VALID_BINARY_SEARCH_PATCH = '''"""Benchmark 01: Off-by-one boundary bug in binary search (FIXED)."""


def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found.

    FIXED: Loop now correctly uses `low <= high` to include boundary elements.
    """
    if not arr:
        return -1

    low = 0
    high = len(arr) - 1

    while low <= high:  # Corrected boundary condition
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1

    return -1
'''

# Patch that still fails the edge case
STILL_FAILING_PATCH = '''def binary_search(arr: list[int], target: int) -> int:
    # Still broken: unchanged loop condition
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low < high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
'''

# Patch that introduces a regression (e.g. breaks empty array baseline test)
REGRESSION_PATCH = '''def binary_search(arr: list[int], target: int) -> int:
    # Regression: crashes on empty array with IndexError
    low = 0
    high = len(arr) - 1
    if arr[0] == target:  # Crashes on empty array!
        return 0
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
'''

# Malformed patch that fails AST parsing
SYNTAX_ERROR_PATCH = '''def binary_search(arr: list[int], target: int) -> int:
    while low <= high  # Missing colon! SyntaxError
        return mid
'''


class MockLLMProvider(LLMProvider):
    """Deterministic mock provider returning pre-computed candidate patches."""

    def __init__(
        self,
        mode: str = "valid",
        custom_patch: Optional[str] = None,
        custom_explanation: str = "Mock patch generated for testing.",
        fixture_id: Optional[str] = None,
        patch_map: Optional[dict[str, str]] = None,
    ):
        """Initializes MockLLMProvider.

        Args:
            mode: One of 'valid', 'still_fails', 'regression', 'syntax_error', or 'custom'.
            custom_patch: Optional explicit patch string to return.
            custom_explanation: Explanatory text for the patch.
            fixture_id: Optional benchmark fixture ID (e.g. 'BM-01', 'BM-02') to auto-select its patch.
            patch_map: Optional dictionary mapping fixture IDs to custom patches.
        """
        self.mode = mode
        self.custom_patch = custom_patch
        self.custom_explanation = custom_explanation
        self.fixture_id = fixture_id
        self.patch_map = patch_map or {}
        self.call_count = 0

    def generate_patch(self, source_code: str, failure: FailureArtifact) -> CandidatePatch:
        """Returns deterministic candidate patch based on configured mode or fixture ID."""
        self.call_count += 1

        # 1. Custom patch takes highest precedence
        if self.custom_patch is not None:
            return CandidatePatch(
                patch_code=self.custom_patch,
                explanation=self.custom_explanation,
                raw_model_response=self.custom_patch,
                provider_name="mock",
            )

        # 2. Patch map lookup for specified fixture_id
        if self.fixture_id and self.fixture_id in self.patch_map:
            patch_code = self.patch_map[self.fixture_id]
            return CandidatePatch(
                patch_code=patch_code,
                explanation=f"Deterministic mock patch mapped for {self.fixture_id}.",
                raw_model_response=patch_code,
                provider_name="mock",
            )

        # 3. Dynamic lookup from benchmark fixture dataset if fixture_id is provided
        if self.fixture_id:
            try:
                from benchmarks.loader import get_fixture_by_id
                fixture = get_fixture_by_id(self.fixture_id)
                if fixture and fixture.candidate_patch:
                    return CandidatePatch(
                        patch_code=fixture.candidate_patch,
                        explanation=f"Deterministic mock patch for {self.fixture_id}.",
                        raw_model_response=fixture.candidate_patch,
                        provider_name="mock",
                    )
            except Exception:
                pass

        # 4. Standard predefined modes
        if self.mode == "valid":
            patch_code = VALID_BINARY_SEARCH_PATCH
            explanation = "Replaced `low < high` with `low <= high` to resolve boundary element search."
        elif self.mode == "still_fails":
            patch_code = STILL_FAILING_PATCH
            explanation = "Attempted patch that leaves off-by-one condition unresolved."
        elif self.mode == "regression":
            patch_code = REGRESSION_PATCH
            explanation = "Attempted patch that resolves property test but breaks empty list baseline test."
        elif self.mode == "syntax_error":
            patch_code = SYNTAX_ERROR_PATCH
            explanation = "Malformed Python patch that triggers SyntaxError."
        elif self.mode == "custom":
            raise ValueError("custom_patch must be provided when mode is 'custom'")
        else:
            raise ValueError(f"Unknown mock provider mode: {self.mode}")

        return CandidatePatch(
            patch_code=patch_code,
            explanation=explanation,
            raw_model_response=patch_code,
            provider_name="mock",
        )

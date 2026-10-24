"""Benchmark BM-01: Binary Search Boundary Defect.

Defect: Incorrect binary-search loop boundary condition (`low < high` instead of `low <= high`).
Expected Verdict: VERIFIED.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-01"
TITLE = "Binary Search Boundary Defect"
DEFECT_CATEGORY = "Boundary Condition / Off-by-One"
EXPECTED_VERDICT = Verdict.VERIFIED
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation uses `while low < high:` which misses targets whenever low == high "
    "(such as boundary positions or singleton arrays). The candidate patch corrects the loop "
    "boundary to `while low <= high:`, successfully locating all elements and passing verification."
)

TARGET_SOURCE = '''"""Target implementation: Binary search with an off-by-one boundary defect."""


def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found.

    BUG: Loop uses `low < high` instead of `low <= high`, which misses the target
    whenever low == high (e.g. single-element arrays or targets at boundary positions).
    """
    if not arr:
        return -1

    low = 0
    high = len(arr) - 1

    while low < high:  # BUG: should be low <= high
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1

    return -1
'''

TEST_SOURCE = '''"""Verification harness: Baseline regressions and Hypothesis boundary properties."""

from hypothesis import given, settings, strategies as st
from target import binary_search


# --- Baseline Unit Tests (pass even on buggy code) ---
def test_baseline_empty():
    assert binary_search([], 10) == -1


def test_baseline_finds_middle():
    assert binary_search([1, 3, 5], 3) == 1


def test_baseline_not_found():
    assert binary_search([2, 4, 6], 5) == -1


# --- Property Tests: First, Last, Singleton, Empty, Absent ---
@settings(max_examples=30, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
def test_property_finds_first_element(arr: list[int]):
    """Invariant: First element must always be found."""
    first_val = arr[0]
    idx = binary_search(arr, first_val)
    assert idx != -1 and arr[idx] == first_val


@settings(max_examples=30, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
def test_property_finds_last_element(arr: list[int]):
    """Invariant: Last element must always be found (fails on buggy low < high)."""
    last_val = arr[-1]
    idx = binary_search(arr, last_val)
    assert idx != -1 and arr[idx] == last_val


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=-1000, max_value=1000))
def test_property_singleton_array(val: int):
    """Invariant: Singleton array target must be found at index 0 (fails on buggy low < high)."""
    assert binary_search([val], val) == 0


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=-1000, max_value=1000))
def test_property_empty_array_always_negative_one(val: int):
    """Invariant: Any lookup in an empty list must return -1."""
    assert binary_search([], val) == -1


@settings(max_examples=25, deadline=None)
@given(
    st.lists(st.integers(min_value=-500, max_value=500), min_size=1, max_size=15).map(sorted),
    st.integers(min_value=600, max_value=1000),
)
def test_property_absent_target(arr: list[int], target: int):
    """Invariant: Absent element must return -1."""
    assert binary_search(arr, target) == -1
'''

CANDIDATE_PATCH = '''"""Fixed implementation of binary search with inclusive boundary condition."""


def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found."""
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

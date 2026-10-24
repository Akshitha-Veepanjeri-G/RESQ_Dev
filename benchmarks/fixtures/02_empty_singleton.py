"""Benchmark BM-02: Empty and Singleton Collections.

Defect: Incorrect handling of empty and singleton inputs (IndexError on collection length < 2).
Expected Verdict: VERIFIED.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-02"
TITLE = "Empty and Singleton Collections Handling"
DEFECT_CATEGORY = "Collection Boundaries / Empty & Singleton"
EXPECTED_VERDICT = Verdict.VERIFIED
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation unconditionally accesses sorted_unique[1] without checking collection "
    "length, triggering IndexError on empty list [] or singleton [x]. The candidate patch checks "
    "if len(sorted_unique) < 2 and returns None, satisfying all empty, singleton, and multi-element properties."
)

TARGET_SOURCE = '''"""Target implementation: Finding second smallest unique element."""

from typing import Optional


def find_second_smallest(values: list[int]) -> Optional[int]:
    """Returns the second smallest unique value from a list of integers,
    or None if the collection contains fewer than two unique values.

    BUG: Unconditionally accesses index [1] of the sorted unique elements
    without verifying collection length, causing IndexError on empty or singleton collections.
    """
    sorted_unique = sorted(set(values))
    return sorted_unique[1]  # BUG: IndexError when len(sorted_unique) < 2
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and Hypothesis empty/singleton edge cases."""

from typing import Optional
from hypothesis import given, settings, strategies as st
from target import find_second_smallest


# --- Baseline Unit Tests (pass on collections with >= 2 distinct elements) ---
def test_baseline_three_elements():
    assert find_second_smallest([10, 20, 30]) == 20


def test_baseline_unsorted_duplicates():
    assert find_second_smallest([5, 1, 5, 3]) == 3


def test_baseline_two_elements():
    assert find_second_smallest([7, 2]) == 7


# --- Property Tests: Empty list, Singleton, and Generalized Invariants ---
def test_property_explicit_empty_collection():
    """Explicit edge case: empty collection must return None."""
    assert find_second_smallest([]) is None


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=-1000, max_value=1000))
def test_property_explicit_singleton_collection(val: int):
    """Explicit edge case: singleton collection must return None."""
    assert find_second_smallest([val]) is None


@settings(max_examples=35, deadline=None)
@given(st.lists(st.integers(min_value=-500, max_value=500), max_size=25))
def test_property_second_smallest_invariants(values: list[int]):
    """Invariant: Returns second smallest unique integer, or None if unique elements < 2."""
    unique = sorted(set(values))
    result = find_second_smallest(values)
    if len(unique) < 2:
        assert result is None, f"Expected None for {values}, got {result}"
    else:
        assert result == unique[1], f"Expected {unique[1]} for {values}, got {result}"
'''

CANDIDATE_PATCH = '''"""Fixed implementation of find_second_smallest handling empty and singleton collections."""

from typing import Optional


def find_second_smallest(values: list[int]) -> Optional[int]:
    """Returns the second smallest unique value from a list of integers,
    or None if the collection contains fewer than two unique values.
    """
    sorted_unique = sorted(set(values))
    if len(sorted_unique) < 2:
        return None
    return sorted_unique[1]
'''

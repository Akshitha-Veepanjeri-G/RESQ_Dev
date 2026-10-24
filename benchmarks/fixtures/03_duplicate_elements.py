"""Benchmark BM-03: Duplicate Elements in Collection Operation.

Defect: Incorrect handling of non-adjacent duplicate values in a collection operation.
Expected Verdict: VERIFIED.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-03"
TITLE = "Duplicate Elements in Collection Operation"
DEFECT_CATEGORY = "Collection Operations / Duplicates"
EXPECTED_VERDICT = Verdict.VERIFIED
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation only compares each element to its immediate predecessor, "
    "correctly removing adjacent duplicates but failing on recurring non-adjacent duplicates "
    "(such as [1, 2, 1]). The candidate patch tracks seen elements globally using a hash set, "
    "preserving insertion order and removing all duplicates."
)

TARGET_SOURCE = '''"""Target implementation: Deduplicating list while preserving first-seen order."""


def deduplicate_preserve_order(items: list[int]) -> list[int]:
    """Removes duplicate integers while preserving their first-seen order.

    BUG: Only filters consecutive adjacent duplicates (similar to unix uniq),
    failing when identical elements recur at non-adjacent positions (e.g. [1, 2, 1]).
    """
    if not items:
        return []
    result = [items[0]]
    for x in items[1:]:
        if x != result[-1]:  # BUG: only checks immediate predecessor
            result.append(x)
    return result
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and Hypothesis duplicate element tests."""

from hypothesis import given, settings, strategies as st
from target import deduplicate_preserve_order


# --- Baseline Unit Tests (pass on clean or adjacent duplicate lists) ---
def test_baseline_empty():
    assert deduplicate_preserve_order([]) == []


def test_baseline_no_duplicates():
    assert deduplicate_preserve_order([1, 2, 3]) == [1, 2, 3]


def test_baseline_adjacent_duplicates():
    assert deduplicate_preserve_order([1, 1, 2, 2, 3]) == [1, 2, 3]


# --- Property Tests: Repeated, Adjacent, and Non-adjacent Duplicates ---
def test_property_repeated_adjacent():
    """All identical elements should reduce to singleton."""
    assert deduplicate_preserve_order([5, 5, 5, 5]) == [5]


def test_property_non_adjacent_duplicates():
    """Non-adjacent duplicates must be filtered out (fails on buggy code)."""
    assert deduplicate_preserve_order([1, 2, 1, 3, 2]) == [1, 2, 3]


@settings(max_examples=35, deadline=None)
@given(st.lists(st.integers(min_value=-50, max_value=50), max_size=25))
def test_property_global_deduplication_and_order(items: list[int]):
    """Invariant: Result contains every unique element exactly once in original first-seen order."""
    res = deduplicate_preserve_order(items)
    # Invariant 1: No duplicates exist
    assert len(res) == len(set(res)), f"Duplicates remained in {res}"
    # Invariant 2: Preserves element set
    assert set(res) == set(items)
    # Invariant 3: Matches first-seen order
    seen = set()
    expected = []
    for x in items:
        if x not in seen:
            seen.add(x)
            expected.append(x)
    assert res == expected
'''

CANDIDATE_PATCH = '''"""Fixed implementation of deduplicate_preserve_order with global seen set."""


def deduplicate_preserve_order(items: list[int]) -> list[int]:
    """Removes duplicate integers while preserving their first-seen order."""
    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result
'''

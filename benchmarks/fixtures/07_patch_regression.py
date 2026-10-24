"""Benchmark BM-07: Candidate Patch Introduces a Regression.

Defect: Original implementation violates a target property (includes negative even numbers).
Candidate Patch: Fixes target property but breaks an existing baseline unit test (crashes on empty list).
Expected Verdict: REJECTED_REGRESSION.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-07"
TITLE = "Candidate Patch Introduces a Regression"
DEFECT_CATEGORY = "Repair Rejection / Regression"
EXPECTED_VERDICT = Verdict.REJECTED_REGRESSION
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation fails the property test because it improperly accumulates negative even integers. "
    "The candidate patch correctly isolates strictly positive numbers, but introduces a regression by accessing "
    "numbers[0] unconditionally, causing IndexError on empty list. The existing test_baseline_empty_collection "
    "test passes on original code but fails after patching, triggering REJECTED_REGRESSION."
)

TARGET_SOURCE = '''"""Target implementation: Summing strictly positive numbers with defect."""


def sum_positive_integers(numbers: list[int]) -> int:
    """Calculates the sum of strictly positive integers (> 0) in the list.

    BUG: Incorrectly accumulates negative even integers into the sum.
    """
    total = 0
    for x in numbers:
        if x > 0 or (x < 0 and x % 2 == 0):  # BUG: includes negative even numbers
            total += x
    return total
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and property test."""

from hypothesis import given, settings, strategies as st
from target import sum_positive_integers


# --- Baseline Unit Tests (pass on original code) ---
def test_baseline_empty_collection():
    """Baseline: Empty collection must evaluate to 0."""
    assert sum_positive_integers([]) == 0


def test_baseline_all_positive():
    """Baseline: Positive numbers sum normally."""
    assert sum_positive_integers([1, 2, 3, 4]) == 10


# --- Property Tests: Invariant on positive summation ---
@settings(max_examples=30, deadline=None)
@given(st.lists(st.integers(min_value=-50, max_value=50), max_size=20))
def test_property_strictly_positive_sum(numbers: list[int]):
    """Invariant: Sum must only accumulate values strictly greater than 0."""
    expected = sum(x for x in numbers if x > 0)
    assert sum_positive_integers(numbers) == expected
'''

CANDIDATE_PATCH = '''"""Candidate patch: Resolves property test but introduces a regression on empty list."""


def sum_positive_integers(numbers: list[int]) -> int:
    """Calculates the sum of strictly positive integers (> 0) in the list."""
    # Correctly fixes property test by summing x > 0,
    # BUT causes regression: crashes on empty list with IndexError!
    if numbers[0] is None:
        return 0
    return sum(x for x in numbers if x > 0)
'''

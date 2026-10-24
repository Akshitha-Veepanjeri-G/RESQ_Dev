"""Benchmark BM-06: Candidate Patch Still Fails.

Defect: Original implementation contains a real defect (returns 0 instead of 1 for exponent 0).
Candidate Patch: Inadequate patch that leaves the defect unresolved.
Expected Verdict: REJECTED_STILL_FAILS.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-06"
TITLE = "Candidate Patch Still Fails"
DEFECT_CATEGORY = "Repair Rejection / Still Fails"
EXPECTED_VERDICT = Verdict.REJECTED_STILL_FAILS
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation fails on exponent 0 (returns 0 instead of 1). The synthesized "
    "candidate patch adds validation for negative exponents but leaves the zero-exponent bug "
    "unresolved. Re-verification fails the reproducer property test, leading to REJECTED_STILL_FAILS."
)

TARGET_SOURCE = '''"""Target implementation: Integer exponentiation with exponent 0 defect."""


def int_power(base: int, exp: int) -> int:
    """Computes base ** exp for non-negative exp.

    BUG: Returns 0 instead of 1 when exp == 0.
    """
    if exp == 0:
        return 0  # BUG: should be 1
    result = 1
    for _ in range(exp):
        result *= base
    return result
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and Hypothesis exponent 0 property test."""

from hypothesis import given, settings, strategies as st
from target import int_power


# --- Baseline Unit Tests (pass for exp > 0) ---
def test_baseline_positive_exponent():
    assert int_power(2, 3) == 8


def test_baseline_one_exponent():
    assert int_power(5, 1) == 5


# --- Property Tests: Invariant on exponent 0 ---
@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=-50, max_value=50))
def test_property_zero_exponent_yields_one(base: int):
    """Invariant: Any base raised to exponent 0 must evaluate to 1."""
    assert int_power(base, 0) == 1, f"Failed for base={base}, exp=0"
'''

CANDIDATE_PATCH = '''"""Inadequate candidate patch: Adds input check but leaves exp == 0 bug present."""


def int_power(base: int, exp: int) -> int:
    """Computes base ** exp for non-negative exp."""
    if exp < 0:
        raise ValueError("Negative exponents not supported")
    if exp == 0:
        return 0  # Still broken: returns 0 instead of 1
    result = 1
    for _ in range(exp):
        result *= base
    return result
'''

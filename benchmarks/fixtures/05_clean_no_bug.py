"""Benchmark BM-05: Clean Implementation.

Defect Category: None; intentionally correct implementation.
Expected Verdict: NO_FAILURE_FOUND.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-05"
TITLE = "Clean Implementation Without Defects"
DEFECT_CATEGORY = "No Defect / Clean Implementation"
EXPECTED_VERDICT = Verdict.NO_FAILURE_FOUND
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Target implementation is completely correct and satisfies all baseline unit tests and "
    "Hypothesis property invariants. The verification pipeline executes exactly one baseline run, "
    "detects no failure, does not invoke the LLM provider, and concludes with NO_FAILURE_FOUND."
)

TARGET_SOURCE = '''"""Target implementation: Intentionally correct integer clamp function."""


def clamp(val: int, min_val: int, max_val: int) -> int:
    """Clamps an integer value within the inclusive range [min_val, max_val].

    Contract:
    - min_val must not exceed max_val; raises ValueError otherwise.
    - Returns min_val if val < min_val, max_val if val > max_val, else val.
    """
    if min_val > max_val:
        raise ValueError("min_val must not exceed max_val")
    return max(min_val, min(val, max_val))
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and property tests that pass completely."""

import pytest
from hypothesis import given, settings, strategies as st
from target import clamp


# --- Baseline Unit Tests ---
def test_baseline_within_range():
    assert clamp(5, 0, 10) == 5


def test_baseline_below_min():
    assert clamp(-5, 0, 10) == 0


def test_baseline_above_max():
    assert clamp(15, 0, 10) == 10


def test_baseline_invalid_range():
    with pytest.raises(ValueError, match="min_val must not exceed max_val"):
        clamp(5, 10, 0)


# --- Property Tests ---
@settings(max_examples=40, deadline=None)
@given(
    st.integers(min_value=-1000, max_value=1000),
    st.integers(min_value=-1000, max_value=1000),
    st.integers(min_value=-1000, max_value=1000),
)
def test_property_clamp_invariants(val: int, bound_a: int, bound_b: int):
    min_val, max_val = sorted([bound_a, bound_b])
    res = clamp(val, min_val, max_val)
    assert min_val <= res <= max_val
    if min_val <= val <= max_val:
        assert res == val
    elif val < min_val:
        assert res == min_val
    else:
        assert res == max_val
'''

CANDIDATE_PATCH = None

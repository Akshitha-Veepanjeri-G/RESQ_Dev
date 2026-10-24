"""Benchmark BM-04: Invalid Inputs and Domain Boundaries.

Defect: Incorrect behavior for explicitly defined invalid inputs or domain boundaries.
Expected Verdict: VERIFIED.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-04"
TITLE = "Invalid Inputs and Domain Boundaries"
DEFECT_CATEGORY = "Input Validation / Domain Boundaries"
EXPECTED_VERDICT = Verdict.VERIFIED
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation fails to validate function domain contracts, causing ZeroDivisionError "
    "on total == 0, and failing to raise ValueError on negative or out-of-range inputs. "
    "The candidate patch explicitly enforces contract boundaries and raises ValueError appropriately."
)

TARGET_SOURCE = '''"""Target implementation: Percentage calculation with unvalidated domain boundaries."""


def calculate_percentage(part: float, total: float) -> float:
    """Calculates percentage: (part / total) * 100.

    Contract:
    - total must be strictly positive (> 0); raises ValueError otherwise.
    - part must satisfy 0.0 <= part <= total; raises ValueError otherwise.
    - Returns rounded percentage as float in [0.0, 100.0].

    BUG: Does not validate domain boundaries. Crashes with ZeroDivisionError when total == 0,
    and returns negative or >100% values for out-of-domain inputs without raising ValueError.
    """
    return round((part / total) * 100.0, 2)
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and Hypothesis domain boundary tests."""

import pytest
from hypothesis import given, settings, strategies as st
from target import calculate_percentage


# --- Baseline Unit Tests (valid happy-path inputs) ---
def test_baseline_standard_percentage():
    assert calculate_percentage(25.0, 100.0) == 25.0


def test_baseline_zero_part():
    assert calculate_percentage(0.0, 50.0) == 0.0


def test_baseline_full_percentage():
    assert calculate_percentage(50.0, 50.0) == 100.0


# --- Property Tests: Boundary conditions and explicit invalid inputs ---
def test_property_zero_total_raises_value_error():
    with pytest.raises(ValueError, match="total must be strictly positive"):
        calculate_percentage(10.0, 0.0)


def test_property_negative_total_raises_value_error():
    with pytest.raises(ValueError, match="total must be strictly positive"):
        calculate_percentage(10.0, -5.0)


def test_property_negative_part_raises_value_error():
    with pytest.raises(ValueError, match="part must be within"):
        calculate_percentage(-1.0, 10.0)


def test_property_part_exceeding_total_raises_value_error():
    with pytest.raises(ValueError, match="part must be within"):
        calculate_percentage(15.0, 10.0)


@settings(max_examples=35, deadline=None)
@given(
    st.floats(min_value=-100.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-100.0, max_value=200.0, allow_nan=False, allow_infinity=False),
)
def test_property_domain_boundary_invariants(part: float, total: float):
    """Invariant: Invalid inputs raise ValueError; valid inputs return [0.0, 100.0]."""
    if total <= 0.0 or part < 0.0 or part > total:
        with pytest.raises(ValueError):
            calculate_percentage(part, total)
    else:
        res = calculate_percentage(part, total)
        assert 0.0 <= res <= 100.0
'''

CANDIDATE_PATCH = '''"""Fixed implementation of calculate_percentage enforcing input contract."""


def calculate_percentage(part: float, total: float) -> float:
    """Calculates percentage: (part / total) * 100."""
    if total <= 0.0:
        raise ValueError("total must be strictly positive")
    if part < 0.0 or part > total:
        raise ValueError("part must be within [0, total]")
    return round((part / total) * 100.0, 2)
'''

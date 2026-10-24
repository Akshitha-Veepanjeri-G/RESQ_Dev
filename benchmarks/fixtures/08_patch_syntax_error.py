"""Benchmark BM-08: Syntax-Invalid Candidate Patch.

Defect: Original implementation contains a defect causing baseline test failure.
Candidate Patch: Syntactically invalid Python code (missing colon, malformed statement).
Expected Verdict: REJECTED_SYNTAX_ERROR.
Expected Status: COMPLETED.
"""

from resq.models import Verdict

ID = "BM-08"
TITLE = "Syntax-Invalid Candidate Patch"
DEFECT_CATEGORY = "Static Analysis / Syntax Error"
EXPECTED_VERDICT = Verdict.REJECTED_SYNTAX_ERROR
EXPECTED_STATUS = "COMPLETED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = None
FAULT_INJECTION = None
EXPLANATION = (
    "Original implementation fails its property test. The candidate patch contains invalid Python "
    "syntax (missing colon in while statement). The AST syntax gate detects and rejects the malformed "
    "patch before scheduling Docker re-verification, yielding REJECTED_SYNTAX_ERROR without wasting "
    "container execution resources."
)

TARGET_SOURCE = '''"""Target implementation: Inverting a boolean flag with defect."""


def invert_flag(flag: bool) -> bool:
    """Inverts a boolean flag.

    BUG: Always returns True regardless of flag value.
    """
    return True  # BUG: should be not flag
'''

TEST_SOURCE = '''"""Verification harness: Baseline tests and boolean inversion property test."""

from hypothesis import given, settings, strategies as st
from target import invert_flag


def test_baseline_inverts_false():
    """Baseline: invert_flag(False) returns True (passes by coincidence)."""
    assert invert_flag(False) is True


@settings(max_examples=10, deadline=None)
@given(st.booleans())
def test_property_inverts_flag(flag: bool):
    """Invariant: invert_flag(flag) must be not flag (fails when flag=True)."""
    assert invert_flag(flag) is (not flag)
'''

CANDIDATE_PATCH = '''"""Malformed patch with invalid Python syntax."""


def invert_flag(flag: bool) -> bool:
    while not flag  # SyntaxError: missing colon
        return False
'''

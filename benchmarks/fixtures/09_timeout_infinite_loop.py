"""Benchmark BM-09: Execution Timeout.

Defect: A deliberately non-terminating infinite loop.
Expected Verdict: TIMEOUT_EXCEEDED.
Expected Status: FAILED.
"""

from resq.models import Verdict

ID = "BM-09"
TITLE = "Execution Timeout Infinite Loop"
DEFECT_CATEGORY = "Resource Ceiling / Timeout Exceeded"
EXPECTED_VERDICT = Verdict.TIMEOUT_EXCEEDED
EXPECTED_STATUS = "FAILED"
REQUIRES_DOCKER = True
TIMEOUT_SECONDS = 2
FAULT_INJECTION = None
EXPLANATION = (
    "Target implementation enters an infinite while True loop during test execution. "
    "The Docker execution runner enforces the configured hard timeout (2s), forcefully terminates "
    "the container process, cleans up the container, and reports TIMEOUT_EXCEEDED with terminal FAILED status."
)

TARGET_SOURCE = '''"""Target implementation: Non-terminating infinite loop defect."""


def compute_infinite_sum(n: int) -> int:
    """Computes accumulation loop.

    BUG: Infinite while loop that never terminates.
    """
    count = 0
    while True:  # Non-terminating infinite loop
        count += 1
    return count
'''

TEST_SOURCE = '''"""Verification harness: Invokes compute_infinite_sum triggering execution timeout."""

from target import compute_infinite_sum


def test_baseline_triggers_infinite_loop():
    """Triggers the infinite loop in compute_infinite_sum."""
    assert compute_infinite_sum(5) == 5
'''

CANDIDATE_PATCH = None

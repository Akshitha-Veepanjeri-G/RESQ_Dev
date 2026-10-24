"""Benchmark BM-10: Infrastructure Failure Fault Injection.

Defect Category: Simulated execution infrastructure failure (daemon unreachable, socket drop).
Expected Verdict: INFRASTRUCTURE_ERROR.
Expected Status: FAILED.
"""

from resq.models import Verdict

ID = "BM-10"
TITLE = "Infrastructure Failure Fault Injection"
DEFECT_CATEGORY = "Infrastructure / Docker Daemon Failure"
EXPECTED_VERDICT = Verdict.INFRASTRUCTURE_ERROR
EXPECTED_STATUS = "FAILED"
REQUIRES_DOCKER = False  # Tested via fault-injected execution environment
TIMEOUT_SECONDS = None
FAULT_INJECTION = "daemon_unreachable"
EXPLANATION = (
    "Simulates an infrastructure failure where the container daemon or execution runtime "
    "fails unexpectedly (e.g. Docker daemon unreachable or socket error). The pipeline "
    "catches InfrastructureError, prevents unhandled crashes, records an INFRASTRUCTURE_ERROR run, "
    "and transitions the verification job to terminal status FAILED."
)

TARGET_SOURCE = '''"""Target implementation: Simple function subjected to container daemon outage."""


def identity_operation(x: int) -> int:
    """Returns the input integer without modification."""
    return x
'''

TEST_SOURCE = '''"""Verification harness: Basic identity check."""

from target import identity_operation


def test_baseline_identity():
    assert identity_operation(42) == 42
'''

CANDIDATE_PATCH = None

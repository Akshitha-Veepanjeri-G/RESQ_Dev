"""Domain schema for RESQ Dev benchmark fixtures."""

from dataclasses import dataclass
from typing import Optional
from resq.models import Verdict


@dataclass(frozen=True)
class BenchmarkFixture:
    """Deterministic specification for a verification benchmark fixture."""

    id: str
    title: str
    defect_category: str
    target_source: str
    test_source: str
    expected_verdict: Verdict
    expected_status: str  # "COMPLETED" or "FAILED"
    explanation: str
    candidate_patch: Optional[str] = None
    requires_docker: bool = True
    timeout_seconds: Optional[int] = None
    fault_injection: Optional[str] = None

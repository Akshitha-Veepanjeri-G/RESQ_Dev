"""UI components, formatting helpers, and presentation elements for RESQ Dev."""

import json
from typing import Any, Dict, Optional, Tuple
import streamlit as st
from resq.models import Verdict
from resq.api.schemas import (
    FailureArtifactResponse,
    HealthResponse,
    JobDetailResponse,
    JobStatus,
    VerificationRunResponse,
)

ACTIVE_JOB_STATUSES = {
    JobStatus.PENDING,
    JobStatus.RUNNING_BASELINE,
    JobStatus.REPAIR_CYCLE_1,
    JobStatus.REPAIR_CYCLE_2,
}

TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.INTERRUPTED,
}

BENCHMARK_FIXTURES: Dict[str, Dict[str, str]] = {
    "01: Off-by-one Binary Search": {
        "title": "Off-by-One Loop Boundary (Binary Search)",
        "defect": "Loop uses low < high instead of low <= high, missing edge targets.",
        "expected_verdict": "VERIFIED",
        "target_filename": "target.py",
        "test_filename": "test_target.py",
        "source_code": '''def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found.

    BUG: Loop uses `low < high` instead of `low <= high`, which misses the target
    whenever low == high (e.g. single-element arrays or targets at the end).
    """
    if not arr:
        return -1

    low = 0
    high = len(arr) - 1

    while low < high:  # BUG: should be low <= high
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1

    return -1
''',
        "invariants_code": '''from hypothesis import given, settings, strategies as st
from target import binary_search

def test_baseline_empty():
    assert binary_search([], 10) == -1

def test_baseline_finds_middle():
    assert binary_search([1, 3, 5], 3) == 1

def test_baseline_not_found():
    assert binary_search([2, 4, 6], 5) == -1

@settings(max_examples=50, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
def test_property_finds_all_existing_elements(arr: list[int]):
    """Invariant: every element physically present in the sorted array must be found."""
    for val in arr:
        idx = binary_search(arr, val)
        assert idx != -1, f"Failed to find {val} in {arr}"
        assert arr[idx] == val
''',
    },
    "02: Empty & Singleton Collections": {
        "title": "Empty & Singleton Collections (IndexError Defect)",
        "defect": "Unconditionally accesses [1] on sorted unique values without verifying length.",
        "expected_verdict": "VERIFIED",
        "target_filename": "target.py",
        "test_filename": "test_target.py",
        "source_code": '''"""Target implementation: Finding second smallest unique element."""

from typing import Optional


def find_second_smallest(values: list[int]) -> Optional[int]:
    """Returns the second smallest unique value from a list of integers,
    or None if the collection contains fewer than two unique values.

    BUG: Unconditionally accesses index [1] of the sorted unique elements
    without verifying collection length, causing IndexError on empty or singleton collections.
    """
    sorted_unique = sorted(set(values))
    return sorted_unique[1]  # BUG: IndexError when len(sorted_unique) < 2
''',
        "invariants_code": '''from typing import Optional
from hypothesis import given, settings, strategies as st
from target import find_second_smallest


def test_baseline_three_elements():
    assert find_second_smallest([10, 20, 30]) == 20


def test_baseline_unsorted_duplicates():
    assert find_second_smallest([5, 1, 5, 3]) == 3


def test_baseline_two_elements():
    assert find_second_smallest([7, 2]) == 7


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
        assert result == unique[1]
''',
    },
    "03: Duplicate Elements Handling": {
        "title": "Duplicate Elements in Sequence Operation",
        "defect": "Only checks adjacent duplicates, failing on recurring non-consecutive duplicates.",
        "expected_verdict": "VERIFIED",
        "target_filename": "target.py",
        "test_filename": "test_target.py",
        "source_code": '''"""Target implementation: Deduplicating list while preserving first-seen order."""


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
''',
        "invariants_code": '''from hypothesis import given, settings, strategies as st
from target import deduplicate_preserve_order


def test_baseline_empty():
    assert deduplicate_preserve_order([]) == []


def test_baseline_no_duplicates():
    assert deduplicate_preserve_order([1, 2, 3]) == [1, 2, 3]


def test_baseline_adjacent_duplicates():
    assert deduplicate_preserve_order([1, 1, 2, 2, 3]) == [1, 2, 3]


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(min_value=-50, max_value=50), max_size=30))
def test_property_no_duplicates_in_result(items: list[int]):
    """Invariant 1: The returned sequence must contain no duplicate values."""
    res = deduplicate_preserve_order(items)
    assert len(res) == len(set(res))


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(min_value=-50, max_value=50), max_size=30))
def test_property_contains_all_unique_elements(items: list[int]):
    """Invariant 2: The returned sequence must contain exactly the set of unique values."""
    res = deduplicate_preserve_order(items)
    assert set(res) == set(items)
''',
    },
    "04: Invalid Input & Domain Boundaries": {
        "title": "Invalid Inputs & Domain Validation (Percentage)",
        "defect": "ZeroDivisionError on total==0 and missing domain range validation.",
        "expected_verdict": "VERIFIED",
        "target_filename": "target.py",
        "test_filename": "test_target.py",
        "source_code": '''"""Target implementation: Percentage calculation with unvalidated domain boundaries."""


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
''',
        "invariants_code": '''import pytest
from hypothesis import given, settings, strategies as st
from target import calculate_percentage


def test_baseline_standard_percentage():
    assert calculate_percentage(25.0, 100.0) == 25.0


def test_baseline_zero_part():
    assert calculate_percentage(0.0, 50.0) == 0.0


def test_baseline_full_percentage():
    assert calculate_percentage(50.0, 50.0) == 100.0


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
''',
    },
    "05: Clean Implementation (No Defect)": {
        "title": "Correct Reference Implementation (No Defect)",
        "defect": "None; intentionally correct clamp function.",
        "expected_verdict": "NO_FAILURE_FOUND",
        "target_filename": "target.py",
        "test_filename": "test_target.py",
        "source_code": '''"""Target implementation: Intentionally correct integer clamp function."""


def clamp(val: int, min_val: int, max_val: int) -> int:
    """Clamps an integer value within the inclusive range [min_val, max_val].

    Contract:
    - min_val must not exceed max_val; raises ValueError otherwise.
    - Returns min_val if val < min_val, max_val if val > max_val, else val.
    """
    if min_val > max_val:
        raise ValueError("min_val must not exceed max_val")
    return max(min_val, min(val, max_val))
''',
        "invariants_code": '''import pytest
from hypothesis import given, settings, strategies as st
from target import clamp


def test_baseline_within_range():
    assert clamp(5, 0, 10) == 5


def test_baseline_below_min():
    assert clamp(-5, 0, 10) == 0


def test_baseline_above_max():
    assert clamp(15, 0, 10) == 10


def test_baseline_invalid_range():
    with pytest.raises(ValueError, match="min_val must not exceed max_val"):
        clamp(5, 10, 0)


@settings(max_examples=50, deadline=None)
@given(
    val=st.integers(min_value=-5000, max_value=5000),
    a=st.integers(min_value=-5000, max_value=5000),
    b=st.integers(min_value=-5000, max_value=5000),
)
def test_property_clamped_result_in_range(val: int, a: int, b: int):
    low = min(a, b)
    high = max(a, b)
    result = clamp(val, low, high)
    assert low <= result <= high
''',
    },
}


def inject_custom_css() -> None:
    """Injects high-polish, modern styles for typography, cards, badges, and layout."""
    st.markdown(
        """
        <style>
        /* Import Google Fonts */
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700;800&display=swap');

        /* Base Typography */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }

        code, pre, .stCode, textarea[data-baseweb="textarea"] {
            font-family: 'JetBrains Mono', "Fira Code", monospace !important;
        }

        /* Hero Banner */
        .resq-hero-container {
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.85) 50%, rgba(15, 23, 42, 0.95) 100%);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 14px;
            padding: 1.6rem 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5), inset 0 1px 0 0 rgba(255, 255, 255, 0.1);
            position: relative;
            overflow: hidden;
        }

        .resq-hero-container::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #38bdf8, #818cf8, #34d399, #f59e0b);
        }

        .resq-hero-title {
            font-size: 2.2rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            background: linear-gradient(120deg, #38bdf8 0%, #a5b4fc 50%, #6ee7b7 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0 0 0.35rem 0;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }

        .resq-hero-subtitle {
            font-size: 1.05rem;
            color: #cbd5e1;
            font-weight: 400;
            margin-bottom: 0.75rem;
        }

        .resq-safety-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 9999px;
            padding: 0.25rem 0.85rem;
            font-size: 0.8rem;
            color: #7dd3fc;
            font-weight: 600;
            margin-top: 0.4rem;
        }

        /* Glassmorphic Cards */
        .resq-card {
            background: rgba(30, 41, 59, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 1.1rem 1.3rem;
            margin-bottom: 1rem;
            backdrop-filter: blur(12px);
        }

        /* Stepper Flow Bar */
        .resq-stepper-wrap {
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
            align-items: center;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 0.7rem 1rem;
            margin: 1.1rem 0;
        }

        .resq-step-item {
            padding: 0.35rem 0.8rem;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            transition: all 0.2s ease;
        }

        .resq-step-active {
            background: rgba(56, 189, 248, 0.22);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.5);
            box-shadow: 0 0 14px rgba(56, 189, 248, 0.25);
        }

        .resq-step-done {
            background: rgba(34, 197, 94, 0.16);
            color: #4ade80;
            border: 1px solid rgba(34, 197, 94, 0.35);
        }

        .resq-step-idle {
            background: rgba(148, 163, 184, 0.08);
            color: #64748b;
            border: 1px solid rgba(148, 163, 184, 0.15);
        }

        .resq-step-arrow {
            color: #475569;
            font-size: 0.8rem;
            font-weight: 700;
        }

        /* Status & Verdict Pill Badges */
        .resq-badge-verified {
            background: linear-gradient(135deg, rgba(34, 197, 94, 0.2) 0%, rgba(16, 185, 129, 0.15) 100%);
            border: 1px solid rgba(34, 197, 94, 0.5);
            border-left: 5px solid #22c55e;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin: 0.75rem 0;
        }

        .resq-badge-rejected {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.2) 0%, rgba(225, 29, 72, 0.15) 100%);
            border: 1px solid rgba(239, 68, 68, 0.5);
            border-left: 5px solid #ef4444;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin: 0.75rem 0;
        }

        .resq-badge-info {
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.15) 0%, rgba(99, 102, 241, 0.1) 100%);
            border: 1px solid rgba(56, 189, 248, 0.4);
            border-left: 5px solid #38bdf8;
            border-radius: 8px;
            padding: 1rem 1.25rem;
            margin: 0.75rem 0;
        }

        .resq-copy-cmd {
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 0.6rem 0.9rem;
            font-family: 'JetBrains Mono', monospace;
            color: #38bdf8;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        /* Tab Polish */
        button[data-baseweb="tab"] {
            font-weight: 600 !important;
            font-size: 0.95rem !important;
            padding: 0.6rem 1.2rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def should_continue_polling(
    job: Optional[JobDetailResponse],
    poll_count: int,
    max_polls: int = 60,
) -> bool:
    """Deterministic, pure logic helper determining whether active polling should continue.

    Invariants:
    1. Polling stops if job is None.
    2. Polling stops if job reaches a terminal status (COMPLETED, FAILED, INTERRUPTED).
    3. Polling stops if poll_count >= max_polls.
    4. Polling continues only while job is in an active in-flight status.
    """
    if job is None:
        return False
    if job.current_status in TERMINAL_JOB_STATUSES:
        return False
    if poll_count >= max_polls:
        return False
    return job.current_status in ACTIVE_JOB_STATUSES


def format_status_badge(status: JobStatus) -> Tuple[str, str]:
    """Returns a display label and alert type for a JobStatus."""
    mapping = {
        JobStatus.PENDING: ("⏳ PENDING (Queued)", "info"),
        JobStatus.RUNNING_BASELINE: ("🔄 RUNNING_BASELINE (Docker Test)", "info"),
        JobStatus.REPAIR_CYCLE_1: ("🛠️ REPAIR_CYCLE_1 (Synthesizing & Verifying)", "info"),
        JobStatus.REPAIR_CYCLE_2: ("🛠️ REPAIR_CYCLE_2 (Bounded Refinement)", "info"),
        JobStatus.COMPLETED: ("✅ COMPLETED (Evaluation Finished)", "success"),
        JobStatus.FAILED: ("❌ FAILED (Fatal Pipeline Error)", "error"),
        JobStatus.INTERRUPTED: ("⚠️ INTERRUPTED (Process Ended Prematurely)", "warning"),
    }
    return mapping.get(status, (f"UNKNOWN ({status})", "info"))


def format_verdict_badge(verdict: Optional[Verdict]) -> Tuple[str, str]:
    """Returns a display label and UI tone for a canonical Verdict."""
    if verdict is None:
        return ("⏳ Unresolved / In Progress", "info")

    mapping = {
        Verdict.VERIFIED: (
            "🟢 VERIFIED — Empirical Verification Passed in Docker Sandbox",
            "success",
        ),
        Verdict.NO_FAILURE_FOUND: (
            "⚪ NO_FAILURE_FOUND — All Baseline & Invariant Tests Passed Cleanly",
            "info",
        ),
        Verdict.REJECTED_STILL_FAILS: (
            "🔴 REJECTED_STILL_FAILS — Candidate Patch Failed the Concrete Reproducer",
            "warning",
        ),
        Verdict.REJECTED_REGRESSION: (
            "🔴 REJECTED_REGRESSION — Candidate Patch Broke Existing Baseline Tests",
            "warning",
        ),
        Verdict.REJECTED_SYNTAX_ERROR: (
            "🟠 REJECTED_SYNTAX_ERROR — Candidate Patch Generated Invalid Python Syntax",
            "warning",
        ),
        Verdict.INSUFFICIENT_EVIDENCE: (
            "🟡 INSUFFICIENT_EVIDENCE — Test Crashed but Output Could Not Be Parsed Into a Reproducer",
            "warning",
        ),
        Verdict.TIMEOUT_EXCEEDED: (
            "⏱️ TIMEOUT_EXCEEDED — Container Execution Exceeded Host-Enforced Deadline",
            "error",
        ),
        Verdict.LLM_ERROR: (
            "⚠️ LLM_ERROR — LLM Provider API Failed, Timed Out, or Returned Malformed Payload",
            "error",
        ),
        Verdict.INFRASTRUCTURE_ERROR: (
            "❌ INFRASTRUCTURE_ERROR — Docker Daemon Unreachable, Image Missing, or Worker Crash",
            "error",
        ),
    }
    return mapping.get(verdict, (f"UNKNOWN VERDICT ({verdict})", "info"))


def format_failing_input_display(input_val: Any) -> str:
    """Formats failing_input cleanly, distinguishing native values from un-serializable envelopes."""
    if input_val is None:
        return "None"
    if isinstance(input_val, dict) and input_val.get("__unserializable__") is True:
        val_type = input_val.get("__type__", "Unknown")
        val_repr = input_val.get("__repr__", "")
        return f"[Un-serializable type {val_type}]\n{val_repr}"
    try:
        return json.dumps(input_val, indent=2)
    except Exception:
        return str(input_val)


def render_header() -> None:
    """Renders the high-polish RESQ Dev hero banner and safety invariants."""
    st.markdown(
        """
        <div class="resq-hero-container">
            <div class="resq-hero-title">
                <span>🛡️</span> RESQ Dev
            </div>
            <div class="resq-hero-subtitle">
                Human-Supervised Python Bug Discovery, Isolated Hypothesis Verification & Safe Repair
            </div>
            <div class="resq-safety-pill">
                🔒 Invariant: Isolated Docker Sandbox (&ndash;&ndash;network none) &bull; Zero repo mutation &bull; Human approval gate
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_health_status(health: HealthResponse) -> None:
    """Renders backend, database, and Docker availability badges with recovery instructions."""
    col1, col2, col3 = st.columns(3)
    with col1:
        if health.status == "ok":
            st.success("API: 🟢 Online (v0.1.0)")
        elif health.status == "degraded":
            st.warning("API: 🟡 Degraded (Sandbox Down)")
        else:
            st.error("API: 🔴 Offline")

    with col2:
        if health.database_connected:
            st.success("Database: 🟢 SQLite Connected")
        else:
            st.error("Database: 🔴 Disconnected")

    with col3:
        if health.docker_available:
            st.success("Sandbox: 🟢 Docker Daemon Ready")
        else:
            st.error("Sandbox: 🔴 Docker Offline")

    if health.status != "ok":
        if not health.docker_available and health.database_connected:
            st.warning(
                "⚠️ **Docker is not running.** Verification tasks require Docker "
                "to isolate untrusted code. Start Docker Desktop with Linux containers."
            )
        elif not health.database_connected:
            st.error(
                "❌ **Backend service is unreachable.** Launch the FastAPI server:\n"
                "`uvicorn resq.api.app:app --host 127.0.0.1 --port 8000 --reload`"
            )


def render_pipeline_stepper(status: JobStatus, runs_count: int, final_verdict: Optional[Verdict]) -> None:
    """Renders an interactive, visually distinct pipeline stepper showing the verification lifecycle."""
    # Define canonical stages
    # 1. Submitted, 2. Baseline Test, 3. Hypothesis Discovery, 4. LLM Synthesis, 5. Re-verification, 6. Human Approval
    step_classes = {
        "submit": "resq-step-done",
        "baseline": "resq-step-idle",
        "discovery": "resq-step-idle",
        "synthesis": "resq-step-idle",
        "reverify": "resq-step-idle",
        "gate": "resq-step-idle",
    }

    if status == JobStatus.PENDING:
        step_classes["baseline"] = "resq-step-active"
    elif status == JobStatus.RUNNING_BASELINE:
        step_classes["baseline"] = "resq-step-active"
    elif status in (JobStatus.REPAIR_CYCLE_1, JobStatus.REPAIR_CYCLE_2):
        step_classes["baseline"] = "resq-step-done"
        step_classes["discovery"] = "resq-step-done"
        step_classes["synthesis"] = "resq-step-done"
        step_classes["reverify"] = "resq-step-active"
    elif status == JobStatus.COMPLETED:
        step_classes["baseline"] = "resq-step-done"
        if final_verdict == Verdict.NO_FAILURE_FOUND:
            step_classes["discovery"] = "resq-step-done"
            step_classes["gate"] = "resq-step-done"
        else:
            step_classes["discovery"] = "resq-step-done"
            step_classes["synthesis"] = "resq-step-done"
            step_classes["reverify"] = "resq-step-done"
            step_classes["gate"] = "resq-step-active" if final_verdict == Verdict.VERIFIED else "resq-step-done"
    elif status in (JobStatus.FAILED, JobStatus.INTERRUPTED):
        step_classes["baseline"] = "resq-step-done"

    html = f"""
    <div class="resq-stepper-wrap">
        <div class="resq-step-item {step_classes['submit']}">1. Ingestion</div>
        <div class="resq-step-arrow">&rarr;</div>
        <div class="resq-step-item {step_classes['baseline']}">2. Docker Baseline</div>
        <div class="resq-step-arrow">&rarr;</div>
        <div class="resq-step-item {step_classes['discovery']}">3. Hypothesis Edge Shrink</div>
        <div class="resq-step-arrow">&rarr;</div>
        <div class="resq-step-item {step_classes['synthesis']}">4. Patch Synthesis</div>
        <div class="resq-step-arrow">&rarr;</div>
        <div class="resq-step-item {step_classes['reverify']}">5. Sandbox Re-verification</div>
        <div class="resq-step-arrow">&rarr;</div>
        <div class="resq-step-item {step_classes['gate']}">6. Human Approval Gate</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_evidence_card(artifact: Optional[FailureArtifactResponse]) -> None:
    """Renders minimized reproducible failure evidence extracted by Hypothesis and pytest."""
    st.markdown("#### 🔍 Reproducible Failure Evidence")
    if not artifact or (not artifact.failing_input and not artifact.assertion_message and not artifact.traceback_raw):
        st.info("No failure artifact was captured during this run (tests ran cleanly or no reproducer found).")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.write("**Exception Type:**")
        st.code(artifact.exception_type or "Unknown Exception", language="text")
        st.write("**Assertion Message:**")
        st.code(artifact.assertion_message or "None", language="text")

    with c2:
        st.write("**Hypothesis Deterministic Seed:**")
        st.code(str(artifact.seed) if artifact.seed is not None else "None", language="text")
        st.write("**Reproducible by Engine:**")
        st.code("Yes (Deterministic)" if artifact.is_reproducible else "No", language="text")

    st.write("**🎯 Minimized Failing Input (Found via Hypothesis Shrinking):**")
    st.code(format_failing_input_display(artifact.failing_input), language="json")

    if artifact.traceback_raw:
        with st.expander("📄 View Captured Traceback", expanded=False):
            st.code(artifact.traceback_raw, language="text")


def render_diff_and_export(run: VerificationRunResponse, original_source: str = "") -> None:
    """Renders candidate patch explanation, unified diff, side-by-side view, and safe manual export controls."""
    st.markdown("#### 📝 Candidate Patch & Unified Diff")

    if run.candidate_patch:
        st.markdown(f"**Synthesized by:** `{run.candidate_patch.provider_name}`")
        if run.candidate_patch.explanation:
            st.info(f"**Model Analysis:** {run.candidate_patch.explanation}")

    if run.unified_diff:
        tab_diff, tab_side_by_side, tab_git = st.tabs([
            "📄 Unified Diff (.patch)",
            "⚖️ Side-by-Side Comparison",
            "🚀 Terminal Git Apply Command",
        ])

        with tab_diff:
            st.code(run.unified_diff, language="diff")

        with tab_side_by_side:
            col_orig, col_fixed = st.columns(2)
            with col_orig:
                st.caption("🔴 Original Code (Buggy)")
                st.code(original_source or "# Original source submitted in Tab 1", language="python")
            with col_fixed:
                st.caption("🟢 Candidate Patched Code (Verified)")
                patch_code = run.candidate_patch.patch_code if run.candidate_patch else "# Patch not available"
                st.code(patch_code, language="python")

        with tab_git:
            patch_filename = f"resq_{run.id[:8]}.patch"
            st.caption("Apply this verified diff directly to your local Git repository safely:")
            st.code(f"git apply {patch_filename}", language="bash")
            st.caption("To test without modifying files: `git apply --check " + patch_filename + "`")

        st.markdown("##### 💾 Safe Human Review & Manual Export Gate")
        st.caption(
            "Explicit Approval Principle: Review this verified diff against your repository. "
            "RESQ Dev does not autonomously edit or commit to your project files."
        )

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="📥 Download .patch File",
                data=run.unified_diff,
                file_name=f"resq_{run.id[:8]}.patch",
                mime="text/x-diff",
                help="Download standard unified diff for manual application using git apply.",
            )
        with col2:
            if run.candidate_patch and run.candidate_patch.patch_code:
                st.download_button(
                    label="📄 Download Candidate Python File",
                    data=run.candidate_patch.patch_code,
                    file_name="candidate_patch.py",
                    mime="text/x-python",
                    help="Download candidate replacement Python code.",
                )
    else:
        st.write("No unified diff available for this run.")


def render_execution_runs(runs: list[VerificationRunResponse], original_source: str = "") -> None:
    """Renders an accordion view of all execution cycles in the job with metric badges."""
    st.markdown("### 📊 Execution Run History")
    if not runs:
        st.info("No execution runs recorded yet.")
        return

    for idx, r in enumerate(runs):
        label, tone = format_verdict_badge(r.verdict)
        title = f"Run {idx + 1}: {r.run_type} (Cycle {r.cycle_index}) — {label}"
        with st.expander(title, expanded=(idx == len(runs) - 1)):
            if r.execution_result:
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Exit Code", r.execution_result.exit_code)
                with c2:
                    st.metric("Sandbox Duration", f"{r.execution_result.duration_seconds:.2f}s")
                with c3:
                    st.metric("Timed Out", "Yes" if r.execution_result.timed_out else "No")

                if r.execution_result.stdout:
                    st.write("**Captured Standard Output:**")
                    st.code(r.execution_result.stdout, language="text")
                if r.execution_result.stderr:
                    st.write("**Captured Standard Error:**")
                    st.code(r.execution_result.stderr, language="text")

            if r.failure_artifact:
                render_evidence_card(r.failure_artifact)

            if r.unified_diff:
                render_diff_and_export(r, original_source=original_source)

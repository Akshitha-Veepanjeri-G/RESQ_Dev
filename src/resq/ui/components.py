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
    }
}


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
    """Renders the RESQ Dev branding, explanation, and human-in-the-loop notice."""
    st.title("🛡️ RESQ Dev")
    st.caption("Human-Supervised Python Bug Discovery & Isolated Verification Assistant")
    st.info(
        "**Human-in-the-Loop Safety Invariant:** RESQ Dev executes candidate patches exclusively "
        "inside isolated, ephemeral Docker sandboxes (`--network none`, `--read-only`, non-root). "
        "It **never** modifies your original source files, and **never** performs automatic Git commits, "
        "merges, or deployments. Verified diffs are exported for explicit developer inspection and adoption."
    )


def render_health_status(health: HealthResponse) -> None:
    """Renders backend, database, and Docker availability badges with recovery instructions."""
    col1, col2, col3 = st.columns(3)
    with col1:
        if health.status == "ok":
            st.success("API: 🟢 Online (v0.1.0)")
        elif health.status == "degraded":
            st.warning("API: 🟡 Degraded (Docker Offline)")
        else:
            st.error("API: 🔴 Offline / Unreachable")

    with col2:
        if health.database_connected:
            st.success("Database: 🟢 SQLite Connected")
        else:
            st.error("Database: 🔴 Disconnected")

    with col3:
        if health.docker_available:
            st.success("Sandbox: 🟢 Docker Daemon Ready")
        else:
            st.error("Sandbox: 🔴 Docker Daemon Down")

    if health.status != "ok":
        if not health.docker_available and health.database_connected:
            st.warning(
                "⚠️ **Docker is not running or unreachable.** Verification tasks require Docker "
                "to isolate untrusted code. Start Docker Desktop with Linux containers."
            )
        elif not health.database_connected:
            st.error(
                "❌ **Backend service is unreachable.** Launch the FastAPI server:\n"
                "`uvicorn resq.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000`"
            )


def render_evidence_card(artifact: Optional[FailureArtifactResponse]) -> None:
    """Renders minimized reproducible failure evidence extracted by Hypothesis and pytest."""
    st.markdown("### 🔍 Reproducible Failure Evidence")
    if not artifact or (not artifact.failing_input and not artifact.assertion_message and not artifact.traceback_raw):
        st.write("No failure artifact was captured during this run (test ran cleanly or no reproducer found).")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.write("**Exception Type:**")
        st.code(artifact.exception_type or "Unknown Exception", language="text")
        st.write("**Assertion Message:**")
        st.code(artifact.assertion_message or "None", language="text")

    with col2:
        st.write("**Hypothesis Deterministic Seed:**")
        st.code(str(artifact.seed) if artifact.seed is not None else "None", language="text")
        st.write("**Reproducible by Engine:**")
        st.code("Yes" if artifact.is_reproducible else "No", language="text")

    st.write("**Minimized Failing Input:**")
    st.code(format_failing_input_display(artifact.failing_input), language="json")

    if artifact.traceback_raw:
        with st.expander("📄 View Captured Traceback", expanded=False):
            st.code(artifact.traceback_raw, language="text")


def render_diff_and_export(run: VerificationRunResponse) -> None:
    """Renders candidate patch explanation, unified diff, and safe manual export controls."""
    st.markdown("### 📝 Candidate Patch & Unified Diff")

    if run.candidate_patch:
        st.write(f"**Synthesized by:** `{run.candidate_patch.provider_name}`")
        if run.candidate_patch.explanation:
            st.info(f"**Model Analysis:** {run.candidate_patch.explanation}")

    if run.unified_diff:
        st.code(run.unified_diff, language="diff")

        st.markdown("#### 💾 Human Review & Manual Export")
        st.caption(
            "Explicit Approval Gate: Review this diff against your repository. "
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


def render_execution_runs(runs: list[VerificationRunResponse]) -> None:
    """Renders an accordion view of all execution cycles in the job."""
    st.markdown("### 📊 Execution Run History")
    if not runs:
        st.write("No execution runs recorded yet.")
        return

    for idx, r in enumerate(runs):
        label, _ = format_verdict_badge(r.verdict)
        title = f"Run {idx}: {r.run_type} (Cycle {r.cycle_index}) — {label}"
        with st.expander(title, expanded=(idx == len(runs) - 1)):
            if r.execution_result:
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("Exit Code", r.execution_result.exit_code)
                with c2:
                    st.metric("Duration", f"{r.execution_result.duration_seconds:.2f}s")
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
                render_diff_and_export(r)

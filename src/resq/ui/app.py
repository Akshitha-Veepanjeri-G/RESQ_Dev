import sys
from pathlib import Path

# Ensure src/ is on sys.path when running directly via `streamlit run src/resq/ui/app.py`
_src_path = Path(__file__).resolve().parent.parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

import time
import streamlit as st
from resq.models import Verdict
from resq.api.schemas import JobStatus
from resq.ui.api_client import (
    ApiClientError,
    ApiConnectionError,
    JobNotFoundError,
    RESQApiClient,
)
from resq.ui.components import (
    BENCHMARK_FIXTURES,
    format_status_badge,
    format_verdict_badge,
    inject_custom_css,
    render_execution_runs,
    render_header,
    render_health_status,
    render_pipeline_stepper,
    should_continue_polling,
)


def main():
    st.set_page_config(
        page_title="RESQ Dev — Verification Assistant",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Inject high-polish modern stylesheet
    inject_custom_css()

    # 1. Initialize session state
    st.session_state.setdefault("api_base_url", "http://127.0.0.1:8000")
    st.session_state.setdefault("active_job_id", None)
    st.session_state.setdefault("is_polling", False)
    st.session_state.setdefault("poll_count", 0)
    st.session_state.setdefault("source_code", "")
    st.session_state.setdefault("invariants_code", "")
    st.session_state.setdefault("target_filename", "target.py")
    st.session_state.setdefault("test_filename", "test_target.py")
    st.session_state.setdefault("history_filter", "All")

    client = RESQApiClient(base_url=st.session_state.api_base_url)

    try:
        render_header()

        # 2. Sidebar controls: Health, Settings, Template Loader, Job History
        with st.sidebar:
            st.markdown("### ⚙️ System Diagnostics")
            api_url_input = st.text_input(
                "API Base URL",
                value=st.session_state.api_base_url,
                help="Host and port of the running RESQ Dev FastAPI service.",
            )
            if api_url_input != st.session_state.api_base_url:
                st.session_state.api_base_url = api_url_input
                client.close()
                client = RESQApiClient(base_url=st.session_state.api_base_url)

            # Query health
            health = client.check_health()
            render_health_status(health)

            st.divider()
            st.markdown("### 📁 1-Click Benchmark Presets")
            st.caption("Load real-world algorithmic defects with property-based Hypothesis invariants.")
            fixture_choice = st.selectbox(
                "Select Benchmark Preset",
                options=list(BENCHMARK_FIXTURES.keys()),
            )
            selected_fixture = BENCHMARK_FIXTURES[fixture_choice]
            
            # Display fixture metadata preview
            if "defect" in selected_fixture:
                st.caption(f"**Defect:** {selected_fixture['defect']}")
                st.caption(f"**Target Verdict:** `{selected_fixture.get('expected_verdict', 'N/A')}`")

            if st.button("📥 Load Preset into Form", use_container_width=True, type="secondary"):
                st.session_state.source_code = selected_fixture["source_code"]
                st.session_state.invariants_code = selected_fixture["invariants_code"]
                st.session_state.target_filename = selected_fixture["target_filename"]
                st.session_state.test_filename = selected_fixture["test_filename"]
                st.success(f"Loaded: {fixture_choice}")
                st.rerun()

            st.divider()
            st.markdown("### 📜 Verification History")
            try:
                recent_jobs = client.list_jobs(limit=25)
                if recent_jobs:
                    # Quick filter
                    filter_options = ["All", "VERIFIED", "REJECTED", "FAILED"]
                    selected_filter = st.selectbox("Filter History", options=filter_options, index=0)

                    filtered_jobs = recent_jobs
                    if selected_filter == "VERIFIED":
                        filtered_jobs = [j for j in recent_jobs if j.final_verdict == Verdict.VERIFIED]
                    elif selected_filter == "REJECTED":
                        filtered_jobs = [
                            j for j in recent_jobs
                            if j.final_verdict and j.final_verdict.value.startswith("REJECTED")
                        ]
                    elif selected_filter == "FAILED":
                        filtered_jobs = [j for j in recent_jobs if j.current_status == JobStatus.FAILED]

                    st.caption(f"Showing {len(filtered_jobs)} of {len(recent_jobs)} jobs")

                    for j in filtered_jobs:
                        v_icon = "🟢" if j.final_verdict == Verdict.VERIFIED else (
                            "🔴" if j.final_verdict and "REJECTED" in j.final_verdict.value else "⚪"
                        )
                        btn_label = f"{v_icon} {j.target_filename} ({j.job_id[:6]})"
                        if st.button(btn_label, key=f"hist_{j.job_id}", use_container_width=True):
                            st.session_state.active_job_id = j.job_id
                            st.session_state.is_polling = False
                            st.session_state.poll_count = 0
                            st.rerun()
                else:
                    st.caption("No verification jobs submitted yet.")
            except (ApiConnectionError, ApiClientError):
                st.caption("Unable to fetch job history (API offline).")

        # 3. Main Stage: Two Tabs
        tab_submit, tab_evidence = st.tabs([
            "📝 1. Ingestion & Invariant Setup",
            "🔍 2. Evidence, Gate & Verified Diff",
        ])

        with tab_submit:
            st.markdown("### 🧪 Submit Python Module for Verification")
            st.caption(
                "Provide your implementation and property-based invariants. "
                "Tests execute strictly inside a resource-throttled Docker sandbox (`--network none`, non-root)."
            )

            col_names_1, col_names_2 = st.columns(2)
            with col_names_1:
                target_fn = st.text_input(
                    "Target Source Filename",
                    value=st.session_state.target_filename,
                    help="Must be a valid Python filename without directory traversal (e.g., target.py).",
                )
            with col_names_2:
                test_fn = st.text_input(
                    "Test Suite Filename",
                    value=st.session_state.test_filename,
                    help="Must be a valid Python filename ending in .py (e.g., test_target.py).",
                )

            col_code_1, col_code_2 = st.columns(2)
            with col_code_1:
                st.markdown("##### 📄 Target Source Code (Under Test)")
                source_input = st.text_area(
                    "Target Python Source Code",
                    value=st.session_state.source_code,
                    height=320,
                    label_visibility="collapsed",
                    placeholder="def my_function(x):\n    # implementation\n    ...",
                    help="The Python module containing potential edge-case bugs (max 128 KiB).",
                )
                source_lines = len(source_input.strip().splitlines()) if source_input.strip() else 0
                st.caption(f"Lines: {source_lines} | Characters: {len(source_input)}")

            with col_code_2:
                st.markdown("##### 🛡️ Invariants & Test Harness (Hypothesis + Pytest)")
                invariants_input = st.text_area(
                    "Test Harness & Invariants Code (Hypothesis / Pytest)",
                    value=st.session_state.invariants_code,
                    height=320,
                    label_visibility="collapsed",
                    placeholder="from hypothesis import given, strategies as st\n\ndef test_property(...):\n    ...",
                    help="Test harness with unit tests and Hypothesis property invariants (max 128 KiB).",
                )
                invariants_lines = len(invariants_input.strip().splitlines()) if invariants_input.strip() else 0
                st.caption(f"Lines: {invariants_lines} | Characters: {len(invariants_input)}")

            col_action_1, col_action_2 = st.columns([2, 1])
            with col_action_1:
                submit_clicked = st.button("🚀 Run RESQ Verification Gate", type="primary", use_container_width=True)
            with col_action_2:
                if st.button("🧹 Clear Editor Form", use_container_width=True):
                    st.session_state.source_code = ""
                    st.session_state.invariants_code = ""
                    st.rerun()

            if submit_clicked:
                # Client-side validation
                if not source_input.strip():
                    st.error("Source code cannot be empty.")
                elif not invariants_input.strip():
                    st.error("Test harness / invariants code cannot be empty.")
                elif not health.database_connected:
                    st.error("Cannot submit: Backend database is offline. Check FastAPI service.")
                else:
                    try:
                        with st.spinner("Submitting verification job to background queue..."):
                            summary = client.submit_job(
                                source_code=source_input,
                                invariants_code=invariants_input,
                                target_filename=target_fn.strip() or "target.py",
                                test_filename=test_fn.strip() or "test_target.py",
                            )
                        st.success(f"Job enqueued: `{summary.job_id}`")
                        st.session_state.active_job_id = summary.job_id
                        st.session_state.is_polling = True
                        st.session_state.poll_count = 0
                        # Update form buffers
                        st.session_state.source_code = source_input
                        st.session_state.invariants_code = invariants_input
                        st.session_state.target_filename = target_fn
                        st.session_state.test_filename = test_fn
                        st.rerun()
                    except ApiClientError as err:
                        st.error(f"Submission rejected: {err.detail}")

        with tab_evidence:
            if not st.session_state.active_job_id:
                st.info("💡 No active verification job selected. Submit a job in Tab 1 or select a recent run from the sidebar.")
            else:
                active_id = st.session_state.active_job_id
                col_header_1, col_header_2 = st.columns([3, 1])
                with col_header_1:
                    st.markdown(f"### Verification Job: `{active_id}`")
                with col_header_2:
                    if st.button("🔄 Refresh Status", use_container_width=True):
                        st.rerun()

                try:
                    job_detail = client.get_job(active_id)

                    # 1. Pipeline Stepper visualization
                    render_pipeline_stepper(
                        status=job_detail.current_status,
                        runs_count=len(job_detail.runs),
                        final_verdict=job_detail.final_verdict,
                    )

                    # 2. Status and Verdict cards
                    st_label, st_tone = format_status_badge(job_detail.current_status)
                    vd_label, vd_tone = format_verdict_badge(job_detail.final_verdict)

                    col_stat_1, col_stat_2 = st.columns(2)
                    with col_stat_1:
                        st.write("**Lifecycle Status:**")
                        if st_tone == "success":
                            st.success(st_label)
                        elif st_tone == "error":
                            st.error(st_label)
                        elif st_tone == "warning":
                            st.warning(st_label)
                        else:
                            st.info(st_label)

                    with col_stat_2:
                        st.write("**Authoritative Verdict:**")
                        if vd_tone == "success":
                            st.success(vd_label)
                        elif vd_tone == "error":
                            st.error(vd_label)
                        elif vd_tone == "warning":
                            st.warning(vd_label)
                        else:
                            st.info(vd_label)

                    # Explicit empirical verification notice if VERIFIED
                    if job_detail.final_verdict == Verdict.VERIFIED:
                        st.markdown(
                            """
                            <div class="resq-badge-verified">
                                <strong>🎉 Empirical Verification Passed:</strong> The candidate patch resolved the concrete reproducer test 
                                and passed all regression test gates inside the isolated Docker sandbox (exit code 0).
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    elif job_detail.final_verdict and "REJECTED" in job_detail.final_verdict.value:
                        st.markdown(
                            f"""
                            <div class="resq-badge-rejected">
                                <strong>🛡️ Patch Rejected by Verification Gate:</strong> {vd_label}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # 3. Render execution runs & evidence
                    render_execution_runs(
                        job_detail.runs,
                        original_source=st.session_state.source_code,
                    )

                    # 4. Bounded automatic polling
                    if st.session_state.is_polling:
                        if should_continue_polling(job_detail, st.session_state.poll_count, max_polls=60):
                            st.session_state.poll_count += 1
                            st.info(
                                f"⏳ Verification in progress (Cycle {st.session_state.poll_count}/60). "
                                "Running Docker tests..."
                            )
                            time.sleep(2.0)
                            st.rerun()
                        else:
                            st.session_state.is_polling = False
                            st.session_state.poll_count = 0
                            if job_detail.current_status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.INTERRUPTED):
                                st.rerun()

                except JobNotFoundError:
                    st.error(f"Job `{active_id}` was not found on the backend.")
                except ApiClientError as err:
                    st.error(f"Failed to fetch job: {err.detail}")

    finally:
        client.close()


if __name__ == "__main__":
    main()

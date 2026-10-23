"""Unit tests for UI components, badge formatters, and polling logic."""

from datetime import datetime, timezone
import pytest
from resq.models import Verdict
from resq.api.schemas import JobDetailResponse, JobStatus
from resq.ui.components import (
    BENCHMARK_FIXTURES,
    format_failing_input_display,
    format_status_badge,
    format_verdict_badge,
    should_continue_polling,
)


class TestVerdictFormatting:
    """Verifies all nine canonical verdicts are mapped to distinct, understandable badges."""

    def test_all_canonical_verdicts_represented(self):
        for v in Verdict:
            label, tone = format_verdict_badge(v)
            assert v.value in label
            assert tone in ("success", "info", "warning", "error")

    def test_verified_verdict_explicit_badge(self):
        label, tone = format_verdict_badge(Verdict.VERIFIED)
        assert "VERIFIED" in label
        assert "Empirical Verification Passed" in label
        assert tone == "success"

    def test_rejections_marked_as_warnings(self):
        for rej in (
            Verdict.REJECTED_STILL_FAILS,
            Verdict.REJECTED_REGRESSION,
            Verdict.REJECTED_SYNTAX_ERROR,
            Verdict.INSUFFICIENT_EVIDENCE,
        ):
            label, tone = format_verdict_badge(rej)
            assert tone == "warning"

    def test_fatal_errors_marked_as_errors(self):
        for err in (Verdict.TIMEOUT_EXCEEDED, Verdict.LLM_ERROR, Verdict.INFRASTRUCTURE_ERROR):
            label, tone = format_verdict_badge(err)
            assert tone == "error"

    def test_none_verdict_handling(self):
        label, tone = format_verdict_badge(None)
        assert "Unresolved" in label
        assert tone == "info"


class TestStatusFormatting:
    """Verifies all seven lifecycle statuses have clear presentation labels."""

    def test_all_statuses_represented(self):
        for s in JobStatus:
            label, tone = format_status_badge(s)
            assert s.value in label
            assert tone in ("info", "success", "error", "warning")

    def test_terminal_statuses(self):
        _, tone_comp = format_status_badge(JobStatus.COMPLETED)
        assert tone_comp == "success"

        _, tone_fail = format_status_badge(JobStatus.FAILED)
        assert tone_fail == "error"

        _, tone_inter = format_status_badge(JobStatus.INTERRUPTED)
        assert tone_inter == "warning"


class TestFailingInputFormatting:
    """Verifies formatting of minimized failure arguments."""

    def test_none_input(self):
        assert format_failing_input_display(None) == "None"

    def test_native_dict_input(self):
        data = {"arr": [1, 2], "target": 2}
        formatted = format_failing_input_display(data)
        assert '"arr"' in formatted
        assert '"target": 2' in formatted

    def test_unserializable_envelope_display(self):
        envelope = {
            "__unserializable__": True,
            "__type__": "set",
            "__repr__": "{1, 2, 3}",
        }
        formatted = format_failing_input_display(envelope)
        assert "[Un-serializable type set]" in formatted
        assert "{1, 2, 3}" in formatted


class TestPollingLogic:
    """Verifies deterministic, bounded polling state machine."""

    def _make_dummy_job(self, status: JobStatus) -> JobDetailResponse:
        return JobDetailResponse(
            id="job-1",
            target_filename="target.py",
            test_filename="test_target.py",
            current_status=status,
            final_verdict=None,
            runs=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def test_polling_continues_for_active_states(self):
        for active in (
            JobStatus.PENDING,
            JobStatus.RUNNING_BASELINE,
            JobStatus.REPAIR_CYCLE_1,
            JobStatus.REPAIR_CYCLE_2,
        ):
            job = self._make_dummy_job(active)
            assert should_continue_polling(job, poll_count=0, max_polls=60) is True
            assert should_continue_polling(job, poll_count=59, max_polls=60) is True

    def test_polling_stops_on_terminal_states(self):
        for term in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.INTERRUPTED):
            job = self._make_dummy_job(term)
            assert should_continue_polling(job, poll_count=5, max_polls=60) is False

    def test_polling_stops_on_max_polls_reached(self):
        job = self._make_dummy_job(JobStatus.RUNNING_BASELINE)
        assert should_continue_polling(job, poll_count=60, max_polls=60) is False
        assert should_continue_polling(job, poll_count=61, max_polls=60) is False

    def test_polling_stops_if_job_none(self):
        assert should_continue_polling(None, poll_count=0, max_polls=60) is False


class TestBenchmarkFixtures:
    """Verifies pre-packaged benchmark fixtures are valid."""

    def test_off_by_one_benchmark_fixture(self):
        assert "01: Off-by-one Binary Search" in BENCHMARK_FIXTURES
        fixture = BENCHMARK_FIXTURES["01: Off-by-one Binary Search"]
        assert "def binary_search" in fixture["source_code"]
        assert "from hypothesis import given" in fixture["invariants_code"]
        assert fixture["target_filename"] == "target.py"
        assert fixture["test_filename"] == "test_target.py"

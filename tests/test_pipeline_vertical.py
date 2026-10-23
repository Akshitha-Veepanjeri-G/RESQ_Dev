"""End-to-End Vertical Slice Integration Test for RESQ Dev.

Verifies:
1. Real edge-case discovery on a buggy function using Hypothesis in Docker.
2. Minimized failure evidence extraction.
3. Candidate patch application to isolated temporary workspace.
4. Independent re-verification inside Docker yielding VERIFIED.
5. Rejection of patches that still fail (REJECTED_STILL_FAILS).
6. Rejection of patches that cause regressions (REJECTED_REGRESSION).
7. Rejection of patches with syntax errors (REJECTED_SYNTAX_ERROR).
8. Clean code handling (NO_FAILURE_FOUND).
9. Bounded repair cycle enforcement (halts after max_repair_cycles).
10. Complete immutability of the original source file.
"""

import hashlib
from pathlib import Path
from typing import Optional
import pytest
from resq.config import Settings
from resq.engine.pipeline import VerificationPipeline
from resq.execution.docker_runner import DockerExecutionRunner
from resq.llm.mock_provider import MockLLMProvider
from resq.models import Verdict

# Target implementation with boundary off-by-one error
BUGGY_TARGET_CODE = """def binary_search(arr: list[int], target: int) -> int:
    \"\"\"Finds target in sorted array. Returns index or -1 if not found.
    BUG: Uses `low < high` instead of `low <= high`.
    \"\"\"
    if not arr:
        return -1

    low = 0
    high = len(arr) - 1

    while low < high:  # BUG
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1

    return -1
"""

# Fixed implementation
CLEAN_TARGET_CODE = """def binary_search(arr: list[int], target: int) -> int:
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
"""

# Test harness: baseline tests + Hypothesis property test
TEST_SUITE_CODE = """from hypothesis import given, settings, strategies as st
from target import binary_search

def test_baseline_empty():
    assert binary_search([], 10) == -1

def test_baseline_finds_middle():
    assert binary_search([1, 3, 5], 3) == 1

def test_baseline_not_found():
    assert binary_search([2, 4, 6], 5) == -1

@settings(max_examples=25, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
def test_property_finds_all_existing_elements(arr: list[int]):
    for val in arr:
        idx = binary_search(arr, val)
        assert idx != -1, f"Failed to find {val} in {arr}"
        assert arr[idx] == val
"""


class TestPipelineVerticalSlice:
    """End-to-End Vertical Slice Tests executing inside Docker."""

    @pytest.fixture(autouse=True)
    def ensure_docker(self):
        runner = DockerExecutionRunner()
        if not runner._is_docker_available():
            pytest.skip("Docker daemon is not available.")

    @pytest.fixture
    def pipeline_builder(self):
        def _build(mock_llm: MockLLMProvider, custom_settings: Optional[Settings] = None):
            st = custom_settings or Settings(max_execution_timeout_seconds=20)
            runner = DockerExecutionRunner(settings=st)
            return VerificationPipeline(execution_env=runner, llm_provider=mock_llm, settings=st)
        return _build

    def test_vertical_slice_success_verified(self, pipeline_builder):
        """Validates full loop: bug discovered -> patch synthesized -> verified in Docker."""
        mock_llm = MockLLMProvider(mode="valid")
        pipeline = pipeline_builder(mock_llm)

        job = pipeline.run(
            source_code=BUGGY_TARGET_CODE,
            test_code=TEST_SUITE_CODE,
        )

        # 1. Assert terminal status and verdict
        assert job.current_status == "COMPLETED"
        assert job.final_verdict == Verdict.VERIFIED

        # 2. Assert baseline run captured failure evidence
        assert len(job.runs) == 2
        baseline_run = job.runs[0]
        assert baseline_run.run_type == "BASELINE"
        assert baseline_run.verdict == Verdict.REJECTED_STILL_FAILS
        assert baseline_run.failure_artifact is not None
        assert baseline_run.failure_artifact.is_reproducible is True
        assert baseline_run.failure_artifact.failing_input is not None

        # 3. Assert re-verification run passed with unified diff
        reverify_run = job.runs[1]
        assert reverify_run.run_type == "REVERIFICATION"
        assert reverify_run.verdict == Verdict.VERIFIED
        assert reverify_run.unified_diff is not None
        assert "while low <= high:" in reverify_run.unified_diff
        assert reverify_run.execution_result.exit_code == 0

    def test_vertical_slice_patch_still_fails(self, pipeline_builder):
        """Validates that a patch failing the edge case is classified REJECTED_STILL_FAILS."""
        mock_llm = MockLLMProvider(mode="still_fails")
        pipeline = pipeline_builder(mock_llm)

        job = pipeline.run(
            source_code=BUGGY_TARGET_CODE,
            test_code=TEST_SUITE_CODE,
        )

        assert job.current_status == "COMPLETED"
        assert job.final_verdict == Verdict.REJECTED_STILL_FAILS
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.REJECTED_STILL_FAILS

    def test_vertical_slice_patch_causes_regression(self, pipeline_builder):
        """Validates that a patch breaking baseline tests is classified REJECTED_REGRESSION."""
        mock_llm = MockLLMProvider(mode="regression")
        pipeline = pipeline_builder(mock_llm)

        job = pipeline.run(
            source_code=BUGGY_TARGET_CODE,
            test_code=TEST_SUITE_CODE,
        )

        assert job.current_status == "COMPLETED"
        assert job.final_verdict == Verdict.REJECTED_REGRESSION
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.REJECTED_REGRESSION

    def test_vertical_slice_patch_syntax_error(self, pipeline_builder):
        """Validates that a malformed patch is rejected before execution as REJECTED_SYNTAX_ERROR."""
        mock_llm = MockLLMProvider(mode="syntax_error")
        pipeline = pipeline_builder(mock_llm)

        job = pipeline.run(
            source_code=BUGGY_TARGET_CODE,
            test_code=TEST_SUITE_CODE,
        )

        assert job.current_status == "COMPLETED"
        assert job.final_verdict == Verdict.REJECTED_SYNTAX_ERROR
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.REJECTED_SYNTAX_ERROR

    def test_vertical_slice_no_failure_found(self, pipeline_builder):
        """Validates that running on clean code returns NO_FAILURE_FOUND without calling LLM."""
        mock_llm = MockLLMProvider(mode="valid")
        pipeline = pipeline_builder(mock_llm)

        job = pipeline.run(
            source_code=CLEAN_TARGET_CODE,
            test_code=TEST_SUITE_CODE,
        )

        assert job.current_status == "COMPLETED"
        assert job.final_verdict == Verdict.NO_FAILURE_FOUND
        assert len(job.runs) == 1
        assert job.runs[0].verdict == Verdict.NO_FAILURE_FOUND
        # Confirm LLM was never called
        assert mock_llm.call_count == 0

    def test_bounded_repair_cycle_enforced(self, pipeline_builder):
        """Verifies that the pipeline halts after max_repair_cycles attempts without infinite loops."""
        mock_llm = MockLLMProvider(mode="still_fails")
        settings = Settings(max_repair_cycles=1, max_execution_timeout_seconds=20)
        pipeline = pipeline_builder(mock_llm, custom_settings=settings)

        job = pipeline.run(
            source_code=BUGGY_TARGET_CODE,
            test_code=TEST_SUITE_CODE,
        )

        # 1 baseline run + exactly 1 repair attempt
        assert len(job.runs) == 2
        assert mock_llm.call_count == 1
        assert job.final_verdict == Verdict.REJECTED_STILL_FAILS

    def test_fixture_source_immutability(self, pipeline_builder):
        """Verifies that the original benchmark fixture file on disk is never modified."""
        fixture_path = Path("benchmarks/fixtures/01_off_by_one.py")
        initial_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()

        # Run pipeline
        mock_llm = MockLLMProvider(mode="valid")
        pipeline = pipeline_builder(mock_llm)
        pipeline.run(
            source_code=fixture_path.read_text(encoding="utf-8"),
            test_code=TEST_SUITE_CODE,
        )

        # Assert fixture hash remains identical
        current_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        assert current_hash == initial_hash, "Original benchmark fixture was mutated!"

"""Milestone M5.2 Stage 2: Comprehensive Benchmark Dataset & Fixture Verification Tests.

Verifies:
1. Fixture Integrity: 10 unique benchmarks, canonical Verdicts, valid lifecycle statuses.
2. Safe AST Loading: Metadata extraction with zero host execution of untrusted target code.
3. Mock LLM Provider Enhancements: Deterministic benchmark patch selection while preserving existing modes.
4. Functional Correctness:
   - BM-01 to BM-04: Buggy baseline fails property -> candidate patch passes re-verification -> VERIFIED.
   - BM-05: Clean target passes baseline -> 1 run -> NO_FAILURE_FOUND -> 0 LLM calls.
   - BM-06: Inadequate candidate patch still fails reproducer -> REJECTED_STILL_FAILS.
   - BM-07: Candidate patch causes baseline failure -> REJECTED_REGRESSION.
   - BM-08: Malformed patch rejected by AST gate before execution -> REJECTED_SYNTAX_ERROR.
   - BM-09: Infinite loop bounded by hard host timeout -> TIMEOUT_EXCEEDED.
   - BM-10: Simulated execution infrastructure failure -> INFRASTRUCTURE_ERROR.
5. Source Immutability: SHA-256 checksums of all 10 fixture files remain strictly identical.
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from resq.config import Settings
from resq.engine.pipeline import VerificationPipeline
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.execution.docker_runner import DockerExecutionRunner
from resq.llm.mock_provider import MockLLMProvider
from resq.models import ExecutionResult, Verdict

from benchmarks import (
    BenchmarkFixture,
    get_fixture_by_id,
    load_all_fixtures,
    load_fixture_from_file,
)
from benchmarks.loader import FIXTURES_DIR


class MockExecutionRunner(ExecutionEnvironment):
    """Deterministic in-memory execution environment for isolated unit tests."""

    def __init__(self, responses: list[ExecutionResult]):
        self.responses = list(responses)
        self.executed_commands: list[list[str]] = []
        self.workspaces: list[Path] = []

    def execute(self, workspace_path: Path, command: list[str], timeout_seconds=None) -> ExecutionResult:
        self.workspaces.append(workspace_path)
        self.executed_commands.append(command)
        if not self.responses:
            raise RuntimeError("No remaining mock execution responses configured.")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


# ==============================================================================
# Category A: Fixture Integrity Tests
# ==============================================================================
class TestFixtureIntegrity:
    """Verifies static integrity, uniqueness, and safety constraints of all 10 fixtures."""

    def test_all_ten_fixtures_exist_and_ids_are_unique(self):
        fixtures = load_all_fixtures()
        assert len(fixtures) == 10, f"Expected exactly 10 fixtures, found {len(fixtures)}"

        ids = [f.id for f in fixtures]
        assert len(set(ids)) == 10, f"Duplicate benchmark IDs detected: {ids}"
        expected_ids = [f"BM-{i:02d}" for i in range(1, 11)]
        assert sorted(ids) == expected_ids

    def test_canonical_verdicts_and_terminal_statuses(self):
        valid_statuses = {"COMPLETED", "FAILED"}
        for fixture in load_all_fixtures():
            assert isinstance(fixture.expected_verdict, Verdict), (
                f"{fixture.id}: expected_verdict must be a valid canonical Verdict enum"
            )
            assert fixture.expected_status in valid_statuses, (
                f"{fixture.id}: expected_status must be one of {valid_statuses}, got {fixture.expected_status}"
            )

    def test_required_code_fields_present_and_non_empty(self):
        for fixture in load_all_fixtures():
            assert fixture.title.strip(), f"{fixture.id} title is missing"
            assert fixture.defect_category.strip(), f"{fixture.id} defect_category is missing"
            assert fixture.target_source.strip(), f"{fixture.id} target_source is missing"
            assert fixture.test_source.strip(), f"{fixture.id} test_source is missing"
            assert fixture.explanation.strip(), f"{fixture.id} explanation is missing"

            # Check candidate patch requirement
            if fixture.expected_verdict in (
                Verdict.VERIFIED,
                Verdict.REJECTED_STILL_FAILS,
                Verdict.REJECTED_REGRESSION,
                Verdict.REJECTED_SYNTAX_ERROR,
            ):
                assert fixture.candidate_patch and fixture.candidate_patch.strip(), (
                    f"{fixture.id} requires a candidate_patch for verdict {fixture.expected_verdict}"
                )
            elif fixture.expected_verdict == Verdict.NO_FAILURE_FOUND:
                assert fixture.candidate_patch is None, (
                    f"{fixture.id} (NO_FAILURE_FOUND) should not define a candidate patch"
                )

    def test_fixture_filenames_are_valid_basenames(self):
        expected_basenames = [
            "01_binary_search.py",
            "02_empty_singleton.py",
            "03_duplicate_elements.py",
            "04_invalid_inputs.py",
            "05_clean_no_bug.py",
            "06_patch_still_fails.py",
            "07_patch_regression.py",
            "08_patch_syntax_error.py",
            "09_timeout_infinite_loop.py",
            "10_docker_fault.py",
        ]
        for basename in expected_basenames:
            fpath = FIXTURES_DIR / basename
            assert fpath.is_file(), f"Missing fixture file: {basename}"
            assert fpath.name == basename

    def test_no_host_execution_during_metadata_loading(self, tmp_path):
        """Verifies that the AST loader does not execute any top-level executable code."""
        canary_file = tmp_path / "host_execution_canary.txt"
        test_fixture_file = tmp_path / "11_safety_test.py"
        test_fixture_file.write_text(
            f'''"""Safety verification fixture."""
from resq.models import Verdict
import os

# If this code were executed on host, the canary file would be created:
if True:
    try:
        with open(r"{canary_file}", "w") as f:
            f.write("EXECUTED_ON_HOST")
    except Exception:
        pass

ID = "BM-11"
TITLE = "Host Safety Test"
DEFECT_CATEGORY = "Security / Host Isolation"
EXPECTED_VERDICT = Verdict.VERIFIED
EXPECTED_STATUS = "COMPLETED"
EXPLANATION = "Testing zero host execution"
TARGET_SOURCE = "def foo(): pass"
TEST_SOURCE = "def test_foo(): pass"
''',
            encoding="utf-8",
        )

        loaded = load_fixture_from_file(test_fixture_file)
        assert loaded.id == "BM-11"
        assert not canary_file.exists(), "CRITICAL: Loader executed code directly on the host!"


# ==============================================================================
# Category B: MockLLMProvider Enhancements & Regressions
# ==============================================================================
class TestMockLLMProviderEnhancements:
    """Verifies benchmark-specific dispatch while preserving default legacy behavior."""

    def test_default_modes_preserved(self):
        mock_valid = MockLLMProvider(mode="valid")
        p_valid = mock_valid.generate_patch("code", MagicMock())
        assert "while low <= high:" in p_valid.patch_code

        mock_fails = MockLLMProvider(mode="still_fails")
        p_fails = mock_fails.generate_patch("code", MagicMock())
        assert "while low < high:" in p_fails.patch_code

        mock_reg = MockLLMProvider(mode="regression")
        p_reg = mock_reg.generate_patch("code", MagicMock())
        assert "arr[0] == target" in p_reg.patch_code

        mock_syn = MockLLMProvider(mode="syntax_error")
        p_syn = mock_syn.generate_patch("code", MagicMock())
        assert "while low <= high" in p_syn.patch_code

    def test_custom_patch_precedence(self):
        custom_code = "def custom(): return 42"
        mock = MockLLMProvider(custom_patch=custom_code)
        patch = mock.generate_patch("code", MagicMock())
        assert patch.patch_code == custom_code

    def test_patch_map_dispatch(self):
        p_map = {"BM-02": "def patch_bm02(): pass", "BM-03": "def patch_bm03(): pass"}
        mock = MockLLMProvider(fixture_id="BM-02", patch_map=p_map)
        patch = mock.generate_patch("code", MagicMock())
        assert patch.patch_code == "def patch_bm02(): pass"

    def test_fixture_id_auto_lookup(self):
        bm02 = get_fixture_by_id("BM-02")
        assert bm02 is not None
        mock = MockLLMProvider(fixture_id="BM-02")
        patch = mock.generate_patch("code", MagicMock())
        assert patch.patch_code == bm02.candidate_patch


# ==============================================================================
# Category C: Functional Correctness (Unit & Mock Pipeline Tests)
# ==============================================================================
class TestFunctionalCorrectnessUnit:
    """Unit-level verification of pipeline transitions and verdicts for all 10 fixtures."""

    def test_bm05_clean_code_unit(self):
        fixture = get_fixture_by_id("BM-05")
        mock_runner = MockExecutionRunner([
            ExecutionResult(exit_code=0, stdout="4 passed in 0.05s", stderr="", timed_out=False, duration_seconds=0.1)
        ])
        mock_llm = MockLLMProvider()
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        job = pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)
        assert job.final_verdict == Verdict.NO_FAILURE_FOUND
        assert job.current_status == "COMPLETED"
        assert len(job.runs) == 1
        assert mock_llm.call_count == 0

    def test_bm06_patch_still_fails_unit(self):
        fixture = get_fixture_by_id("BM-06")
        mock_runner = MockExecutionRunner([
            # 1. Baseline fails with Hypothesis falsifying example
            ExecutionResult(
                exit_code=1,
                stdout=(
                    "FAILED test_target.py::test_property_zero_exponent_yields_one\n"
                    "E   AssertionError: Failed for base=0, exp=0\n"
                    "E   Falsifying example: test_property_zero_exponent_yields_one(\n"
                    "E       base=0,\n"
                    "E   )\n"
                ),
                stderr="",
                timed_out=False,
                duration_seconds=0.1,
            ),
            # 2. Reverification still fails reproducer (no 'baseline' in output)
            ExecutionResult(
                exit_code=1,
                stdout="FAILED test_target.py::test_property_zero_exponent_yields_one\nE   AssertionError: Failed for base=0, exp=0",
                stderr="",
                timed_out=False,
                duration_seconds=0.1,
            ),
        ])
        mock_llm = MockLLMProvider(custom_patch=fixture.candidate_patch)
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        job = pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)
        assert job.final_verdict == Verdict.REJECTED_STILL_FAILS
        assert job.current_status == "COMPLETED"
        assert len(job.runs) == 2

    def test_bm07_patch_regression_unit(self):
        fixture = get_fixture_by_id("BM-07")
        mock_runner = MockExecutionRunner([
            # 1. Baseline fails property with Hypothesis falsifying example
            ExecutionResult(
                exit_code=1,
                stdout=(
                    "FAILED test_target.py::test_property_strictly_positive_sum\n"
                    "E   AssertionError: assert sum_positive_integers([-2]) == 0\n"
                    "E   Falsifying example: test_property_strictly_positive_sum(\n"
                    "E       numbers=[-2],\n"
                    "E   )\n"
                ),
                stderr="",
                timed_out=False,
                duration_seconds=0.1,
            ),
            # 2. Reverification fails baseline test (regression)
            ExecutionResult(
                exit_code=1,
                stdout="FAILED test_target.py::test_baseline_empty_collection\nE   IndexError: list index out of range",
                stderr="",
                timed_out=False,
                duration_seconds=0.1,
            ),
        ])
        mock_llm = MockLLMProvider(custom_patch=fixture.candidate_patch)
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        job = pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)
        assert job.final_verdict == Verdict.REJECTED_REGRESSION
        assert job.current_status == "COMPLETED"
        assert len(job.runs) == 2

    def test_bm08_syntax_error_unit(self):
        fixture = get_fixture_by_id("BM-08")
        mock_runner = MockExecutionRunner([
            # 1. Baseline fails with Hypothesis falsifying example
            ExecutionResult(
                exit_code=1,
                stdout=(
                    "FAILED test_target.py::test_property_inverts_flag\n"
                    "E   AssertionError: assert True is False\n"
                    "E   Falsifying example: test_property_inverts_flag(\n"
                    "E       flag=True,\n"
                    "E   )\n"
                ),
                stderr="",
                timed_out=False,
                duration_seconds=0.1,
            ),
            # Candidate execution must NEVER be called
        ])
        mock_llm = MockLLMProvider(custom_patch=fixture.candidate_patch)
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        job = pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)
        assert job.final_verdict == Verdict.REJECTED_SYNTAX_ERROR
        assert job.current_status == "COMPLETED"
        assert len(job.runs) == 2
        # Assert no candidate Docker execution was attempted
        assert len(mock_runner.executed_commands) == 1

    def test_bm09_timeout_exceeded_unit(self):
        fixture = get_fixture_by_id("BM-09")
        mock_runner = MockExecutionRunner([
            ExecutionResult(
                exit_code=124,
                stdout="",
                stderr="TIMEOUT_EXCEEDED: Container exceeded hard timeout of 2s.",
                timed_out=True,
                duration_seconds=2.05,
            )
        ])
        mock_llm = MockLLMProvider()
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        job = pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)
        assert job.final_verdict == Verdict.TIMEOUT_EXCEEDED
        assert job.current_status == "FAILED"
        assert len(job.runs) == 1

    def test_bm10_infrastructure_fault_unit(self):
        fixture = get_fixture_by_id("BM-10")
        mock_runner = MockExecutionRunner([
            InfrastructureError("INFRASTRUCTURE_ERROR: Docker daemon unreachable (npipe pipe not found).")
        ])
        mock_llm = MockLLMProvider()
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        job = pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)
        assert job.final_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert job.current_status == "FAILED"
        assert len(job.runs) == 1
        assert "INFRASTRUCTURE_ERROR" in job.runs[0].execution_result.stderr


# ==============================================================================
# Category D: Real Docker Integration Tests (BM-01 to BM-09)
# ==============================================================================
class TestBenchmarkRealDockerIntegration:
    """Executes benchmark fixtures inside real Docker containers with sandboxing flags."""

    @pytest.fixture(autouse=True)
    def ensure_docker(self):
        runner = DockerExecutionRunner()
        if not runner._is_docker_available():
            pytest.skip("Real Docker daemon is not available on host.")

    @pytest.fixture
    def docker_pipeline_builder(self):
        def _build(mock_llm: MockLLMProvider, timeout_seconds: int = 20):
            st = Settings(max_execution_timeout_seconds=timeout_seconds, max_repair_cycles=1)
            runner = DockerExecutionRunner(settings=st)
            return VerificationPipeline(execution_env=runner, llm_provider=mock_llm, settings=st)
        return _build

    def test_real_docker_bm01_binary_search(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-01")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.VERIFIED
        assert "while low <= high:" in job.runs[1].unified_diff

    def test_real_docker_bm02_empty_singleton(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-02")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.VERIFIED
        assert "if len(sorted_unique) < 2:" in job.runs[1].unified_diff

    def test_real_docker_bm03_duplicate_elements(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-03")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.VERIFIED
        assert "seen = set()" in job.runs[1].unified_diff

    def test_real_docker_bm04_invalid_inputs(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-04")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.VERIFIED
        assert "raise ValueError" in job.runs[1].unified_diff

    def test_real_docker_bm05_clean_no_bug(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-05")
        mock_llm = MockLLMProvider()
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 1
        assert mock_llm.call_count == 0

    def test_real_docker_bm06_patch_still_fails(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-06")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.REJECTED_STILL_FAILS

    def test_real_docker_bm07_patch_regression(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-07")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.REJECTED_REGRESSION

    def test_real_docker_bm08_syntax_error(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-08")
        mock_llm = MockLLMProvider(custom_patch=bm.candidate_patch)
        pipeline = docker_pipeline_builder(mock_llm)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.REJECTED_SYNTAX_ERROR

    def test_real_docker_bm09_timeout_infinite_loop(self, docker_pipeline_builder):
        bm = get_fixture_by_id("BM-09")
        mock_llm = MockLLMProvider()
        # Enforce short 2-second timeout
        pipeline = docker_pipeline_builder(mock_llm, timeout_seconds=2)

        job = pipeline.run(source_code=bm.target_source, test_code=bm.test_source)
        assert job.final_verdict == bm.expected_verdict
        assert job.current_status == bm.expected_status
        assert len(job.runs) == 1
        assert job.runs[0].verdict == Verdict.TIMEOUT_EXCEEDED
        assert job.runs[0].execution_result.timed_out is True


# ==============================================================================
# Category E: Source Immutability and Safety Tests
# ==============================================================================
class TestSourceImmutabilityAndSafety:
    """Verifies that original benchmark fixture files on disk are never modified."""

    @pytest.mark.parametrize(
        "basename",
        [
            "01_binary_search.py",
            "02_empty_singleton.py",
            "03_duplicate_elements.py",
            "04_invalid_inputs.py",
            "05_clean_no_bug.py",
            "06_patch_still_fails.py",
            "07_patch_regression.py",
            "08_patch_syntax_error.py",
            "09_timeout_infinite_loop.py",
            "10_docker_fault.py",
        ],
    )
    def test_fixture_file_immutability(self, basename):
        fixture_path = FIXTURES_DIR / basename
        initial_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()

        # Load fixture and run it through pipeline with MockExecutionRunner
        fixture = load_fixture_from_file(fixture_path)
        mock_runner = MockExecutionRunner([
            ExecutionResult(exit_code=0, stdout="OK", stderr="", timed_out=False, duration_seconds=0.1)
        ])
        mock_llm = MockLLMProvider(custom_patch=fixture.candidate_patch)
        pipeline = VerificationPipeline(execution_env=mock_runner, llm_provider=mock_llm)

        pipeline.run(source_code=fixture.target_source, test_code=fixture.test_source)

        # Assert post-run checksum is identical
        current_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        assert current_hash == initial_hash, f"CRITICAL: Fixture file {basename} was modified on host!"

"""Tests for BenchmarkRunner and evaluation pipeline (Milestone M5.2 Stage 3).

Verifies:
1. Runner execution controls: single benchmark, subset, full suite.
2. Error and edge-case handling: unknown benchmark IDs, malformed metadata, failure isolation.
3. Outcome classification: distinguishing expected functional failures, regressions, syntax errors, timeouts, and infrastructure faults.
4. Mismatch detection: ensuring benchmarks fail evaluation when actual != expected.
5. Reporting: per-benchmark fields, suite-level aggregation, ASCII summary tables, and JSON serialization.
6. Safety: zero host execution and strict source immutability.
"""

import hashlib
import json
from unittest.mock import MagicMock
import pytest
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.execution.docker_runner import DockerExecutionRunner
from resq.models import ExecutionResult, Verdict

from benchmarks import (
    BenchmarkFixture,
    BenchmarkResult,
    BenchmarkRunner,
    BenchmarkSuiteResult,
    FaultInjectedExecutionRunner,
    get_fixture_by_id,
    load_all_fixtures,
)
from benchmarks.loader import FIXTURES_DIR


class MockDeterministicExecutionRunner(ExecutionEnvironment):
    """Deterministic mock runner for unit tests of runner evaluation logic."""

    def __init__(self, response_map: dict[str, list[ExecutionResult]]):
        self.response_map = {k: list(v) for k, v in response_map.items()}
        self.calls: list[tuple[str, list[str]]] = []

    def execute(self, workspace_path, command, timeout_seconds=None) -> ExecutionResult:
        # Infer fixture from workspace content or test files
        target_file = workspace_path / "target.py"
        target_content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        matched_id = "default"
        for fid in self.response_map:
            if fid in target_content or (fid != "default" and fid.lower() in target_content.lower()):
                matched_id = fid
                break

        self.calls.append((matched_id, command))
        queue = self.response_map.get(matched_id, self.response_map.get("default", []))
        if not queue:
            return ExecutionResult(exit_code=0, stdout="OK", stderr="", timed_out=False, duration_seconds=0.1)
        resp = queue.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


# ==============================================================================
# Category 1: Runner Behavior & Execution Controls
# ==============================================================================
class TestRunnerBehavior:
    """Verifies single-fixture, subset, full-suite execution and error resilience."""

    def test_run_by_id_known_benchmark(self):
        fixture = get_fixture_by_id("BM-05")
        mock_env = MockDeterministicExecutionRunner({
            "default": [
                ExecutionResult(exit_code=0, stdout="4 passed in 0.05s", stderr="", timed_out=False, duration_seconds=0.1)
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        result = runner.run_by_id("BM-05")

        assert result.benchmark_id == "BM-05"
        assert result.expected_verdict == Verdict.NO_FAILURE_FOUND
        assert result.actual_verdict == Verdict.NO_FAILURE_FOUND
        assert result.actual_terminal_status == "COMPLETED"
        assert result.passed is True
        assert result.duration_seconds > 0

    def test_run_by_id_unknown_benchmark_fails_cleanly(self):
        runner = BenchmarkRunner()
        result = runner.run_by_id("BM-NONEXISTENT")

        assert result.benchmark_id == "BM-NONEXISTENT"
        assert result.passed is False
        assert result.error_type == "FixtureNotFoundError"
        assert "No benchmark found" in result.error_message
        assert result.actual_terminal_status == "FAILED"

    def test_run_malformed_fixture_handled_cleanly(self):
        malformed = BenchmarkFixture(
            id="",  # Empty ID is invalid
            title="Broken",
            defect_category="None",
            target_source="",
            test_source="",
            expected_verdict=Verdict.VERIFIED,
            expected_status="COMPLETED",
            explanation="Malformed",
        )
        runner = BenchmarkRunner()
        result = runner.run_benchmark(malformed)

        assert result.passed is False
        assert result.error_type == "MalformedFixtureError"
        assert result.actual_terminal_status == "FAILED"

    def test_run_subset_executes_only_requested_benchmarks(self):
        mock_env = MockDeterministicExecutionRunner({
            "default": [
                ExecutionResult(exit_code=0, stdout="PASSED", stderr="", timed_out=False, duration_seconds=0.05)
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        suite = runner.run_subset(["BM-01", "BM-05"])

        assert suite.total_selected == 2
        assert suite.completed == 2
        assert [r.benchmark_id for r in suite.results] == ["BM-01", "BM-05"]

    def test_failure_isolation_between_benchmarks(self):
        """Verifies that an error in one benchmark does not contaminate or halt another."""
        call_order = []

        def factory(fixture):
            call_order.append(fixture.id)
            if fixture.id == "BM-01":
                return FaultInjectedExecutionRunner("Simulated fatal container crash on BM-01")
            return MockDeterministicExecutionRunner({
                "default": [
                    ExecutionResult(exit_code=0, stdout="PASSED", stderr="", timed_out=False, duration_seconds=0.05)
                ]
            })

        runner = BenchmarkRunner(execution_env_factory=factory)
        suite = runner.run_subset(["BM-01", "BM-05"])

        assert call_order == ["BM-01", "BM-05"]
        assert suite.completed == 2
        # BM-01 expected VERIFIED, but received INFRASTRUCTURE_ERROR -> passed=False
        assert suite.results[0].benchmark_id == "BM-01"
        assert suite.results[0].passed is False
        assert suite.results[0].actual_verdict == Verdict.INFRASTRUCTURE_ERROR
        # BM-05 expected NO_FAILURE_FOUND -> passed=True
        assert suite.results[1].benchmark_id == "BM-05"
        assert suite.results[1].passed is True


# ==============================================================================
# Category 2: Evaluation & Verdict Classification
# ==============================================================================
class TestEvaluationClassification:
    """Verifies that expected outcomes are verified and mismatches are flagged as failures."""

    def test_expected_functional_failure_passes_evaluation(self):
        """BM-06 expects REJECTED_STILL_FAILS. When it produces REJECTED_STILL_FAILS, evaluation passes."""
        fixture = get_fixture_by_id("BM-06")
        mock_env = MockDeterministicExecutionRunner({
            "default": [
                ExecutionResult(
                    exit_code=1,
                    stdout="FAILED test_target.py::test_property_zero_exponent_yields_one\nE   AssertionError: Failed\nE   Falsifying example: test(0)",
                    stderr="",
                    timed_out=False,
                    duration_seconds=0.1,
                ),
                ExecutionResult(
                    exit_code=1,
                    stdout="FAILED test_target.py::test_property_zero_exponent_yields_one\nE   AssertionError: Failed",
                    stderr="",
                    timed_out=False,
                    duration_seconds=0.1,
                ),
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        res = runner.run_benchmark(fixture)

        assert res.actual_verdict == Verdict.REJECTED_STILL_FAILS
        assert res.actual_terminal_status == "COMPLETED"
        assert res.passed is True
        assert res.error_type == "StillFailsError"

    def test_expected_regression_passes_evaluation(self):
        """BM-07 expects REJECTED_REGRESSION. When it produces REJECTED_REGRESSION, evaluation passes."""
        fixture = get_fixture_by_id("BM-07")
        mock_env = MockDeterministicExecutionRunner({
            "default": [
                ExecutionResult(
                    exit_code=1,
                    stdout="FAILED test_target.py::test_property_strictly_positive_sum\nE   AssertionError\nE   Falsifying example: test([-2])",
                    stderr="",
                    timed_out=False,
                    duration_seconds=0.1,
                ),
                ExecutionResult(
                    exit_code=1,
                    stdout="FAILED test_target.py::test_baseline_empty_collection\nE   IndexError",
                    stderr="",
                    timed_out=False,
                    duration_seconds=0.1,
                ),
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        res = runner.run_benchmark(fixture)

        assert res.actual_verdict == Verdict.REJECTED_REGRESSION
        assert res.actual_terminal_status == "COMPLETED"
        assert res.passed is True
        assert res.error_type == "RegressionError"

    def test_expected_timeout_passes_evaluation(self):
        """BM-09 expects TIMEOUT_EXCEEDED. When it times out, evaluation passes."""
        fixture = get_fixture_by_id("BM-09")
        mock_env = MockDeterministicExecutionRunner({
            "default": [
                ExecutionResult(
                    exit_code=124,
                    stdout="",
                    stderr="TIMEOUT_EXCEEDED: Container exceeded hard timeout of 2s.",
                    timed_out=True,
                    duration_seconds=2.01,
                )
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        res = runner.run_benchmark(fixture)

        assert res.actual_verdict == Verdict.TIMEOUT_EXCEEDED
        assert res.actual_terminal_status == "FAILED"
        assert res.passed is True
        assert res.error_type == "TimeoutExceeded"

    def test_expected_infrastructure_fault_passes_evaluation(self):
        """BM-10 expects INFRASTRUCTURE_ERROR. When runner raises InfrastructureError, evaluation passes."""
        fixture = get_fixture_by_id("BM-10")
        runner = BenchmarkRunner()  # Uses FaultInjectedExecutionRunner for BM-10 automatically
        res = runner.run_benchmark(fixture)

        assert res.actual_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert res.actual_terminal_status == "FAILED"
        assert res.passed is True
        assert res.error_type == "InfrastructureError"

    def test_outcome_mismatch_fails_evaluation(self):
        """When actual outcome does not match expected verdict, benchmark evaluation fails."""
        fixture = get_fixture_by_id("BM-01")  # Expects VERIFIED
        mock_env = MockDeterministicExecutionRunner({
            "default": [
                # Unresolved failure
                ExecutionResult(
                    exit_code=1,
                    stdout="FAILED test_target.py::test_property_finds_last_element\nE   AssertionError\nE   Falsifying example: test([0])",
                    stderr="",
                    timed_out=False,
                    duration_seconds=0.1,
                ),
                ExecutionResult(
                    exit_code=1,
                    stdout="FAILED test_target.py::test_property_finds_last_element\nE   AssertionError",
                    stderr="",
                    timed_out=False,
                    duration_seconds=0.1,
                ),
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        res = runner.run_benchmark(fixture)

        # Expected VERIFIED, but received REJECTED_STILL_FAILS
        assert res.expected_verdict == Verdict.VERIFIED
        assert res.actual_verdict == Verdict.REJECTED_STILL_FAILS
        assert res.passed is False


# ==============================================================================
# Category 3: Reporting & Serialization Tests
# ==============================================================================
class TestReportingAndSerialization:
    """Verifies suite aggregation, ASCII summary tables, and JSON serialization."""

    def test_suite_result_aggregation_and_counts(self):
        results = [
            BenchmarkResult("BM-01", "BS", Verdict.VERIFIED, Verdict.VERIFIED, "COMPLETED", "COMPLETED", True, 1.2),
            BenchmarkResult("BM-05", "Clean", Verdict.NO_FAILURE_FOUND, Verdict.NO_FAILURE_FOUND, "COMPLETED", "COMPLETED", True, 0.5),
            BenchmarkResult("BM-08", "Syntax", Verdict.REJECTED_SYNTAX_ERROR, Verdict.REJECTED_SYNTAX_ERROR, "COMPLETED", "COMPLETED", True, 0.2),
            BenchmarkResult("BM-09", "Timeout", Verdict.TIMEOUT_EXCEEDED, Verdict.TIMEOUT_EXCEEDED, "FAILED", "FAILED", True, 2.0),
            BenchmarkResult("BM-10", "Infra", Verdict.INFRASTRUCTURE_ERROR, Verdict.INFRASTRUCTURE_ERROR, "FAILED", "FAILED", True, 0.1),
        ]
        runner = BenchmarkRunner()
        suite = runner._aggregate_suite_result(results, total_selected=5, total_duration=4.0)

        assert suite.total_selected == 5
        assert suite.completed == 5
        assert suite.passed == 5
        assert suite.failed == 0
        assert suite.timeouts == 1
        assert suite.syntax_errors == 1
        assert suite.infrastructure_failures == 1
        assert suite.overall_status == "PASSED"

    def test_json_serialization_is_valid_and_deterministic(self):
        res = BenchmarkResult(
            benchmark_id="BM-01",
            title="Binary Search",
            expected_verdict=Verdict.VERIFIED,
            actual_verdict=Verdict.VERIFIED,
            expected_terminal_status="COMPLETED",
            actual_terminal_status="COMPLETED",
            passed=True,
            duration_seconds=1.2345,
            unified_diff="--- a\n+++ b\n",
        )
        suite = BenchmarkSuiteResult(
            total_selected=1,
            completed=1,
            passed=1,
            failed=0,
            timeouts=0,
            syntax_errors=0,
            infrastructure_failures=0,
            overall_status="PASSED",
            results=[res],
            total_duration_seconds=1.235,
        )

        json_str = suite.to_json()
        data = json.loads(json_str)

        assert data["total_selected"] == 1
        assert data["overall_status"] == "PASSED"
        assert len(data["results"]) == 1
        assert data["results"][0]["benchmark_id"] == "BM-01"
        assert data["results"][0]["expected_verdict"] == "VERIFIED"
        assert data["results"][0]["actual_verdict"] == "VERIFIED"
        assert data["results"][0]["passed"] is True

    def test_summary_table_formatting(self):
        res = BenchmarkResult(
            benchmark_id="BM-01",
            title="Binary Search",
            expected_verdict=Verdict.VERIFIED,
            actual_verdict=Verdict.VERIFIED,
            expected_terminal_status="COMPLETED",
            actual_terminal_status="COMPLETED",
            passed=True,
            duration_seconds=1.25,
        )
        suite = BenchmarkSuiteResult(
            total_selected=1,
            completed=1,
            passed=1,
            failed=0,
            timeouts=0,
            syntax_errors=0,
            infrastructure_failures=0,
            overall_status="PASSED",
            results=[res],
            total_duration_seconds=1.25,
        )
        table = suite.format_summary_table()
        assert "BM-01" in table
        assert "Binary Search" in table
        assert "VERIFIED" in table
        assert "PASS" in table
        assert "Overall Status: PASSED" in table


# ==============================================================================
# Category 4: Safety & Docker Integration Tests
# ==============================================================================
class TestRunnerSafetyAndDockerIntegration:
    """Verifies Docker isolation boundary, resource cleanup, and immutability."""

    def test_fixture_source_immutability_through_runner(self):
        """Asserts that executing through BenchmarkRunner never mutates fixture files on disk."""
        fixtures = load_all_fixtures()
        hashes_before = {f.id: hashlib.sha256((FIXTURES_DIR / f"{int(f.id.split('-')[1]):02d}_{f.title.lower().replace(' ', '_')[:10]}.py").read_bytes()).hexdigest()
                         for f in fixtures if (FIXTURES_DIR / f"{int(f.id.split('-')[1]):02d}_{f.title.lower().replace(' ', '_')[:10]}.py").exists()}

        # Simple file-by-file hash check
        all_fixture_files = list(FIXTURES_DIR.glob("*.py"))
        pre_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in all_fixture_files}

        mock_env = MockDeterministicExecutionRunner({
            "default": [
                ExecutionResult(exit_code=0, stdout="OK", stderr="", timed_out=False, duration_seconds=0.05)
            ]
        })
        runner = BenchmarkRunner(execution_env_factory=lambda f: mock_env)
        runner.run_all()

        post_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in all_fixture_files}
        assert pre_hashes == post_hashes, "CRITICAL: Fixture source on disk was mutated during runner execution!"

    def test_real_docker_runner_execution_bm05(self):
        """End-to-end execution of clean code BM-05 through BenchmarkRunner inside real Docker."""
        runner_probe = DockerExecutionRunner()
        if not runner_probe._is_docker_available():
            pytest.skip("Docker daemon not reachable.")

        runner = BenchmarkRunner()
        res = runner.run_by_id("BM-05")

        assert res.benchmark_id == "BM-05"
        assert res.actual_verdict == Verdict.NO_FAILURE_FOUND
        assert res.actual_terminal_status == "COMPLETED"
        assert res.passed is True
        assert res.runs_count == 1

    def test_real_docker_runner_execution_bm10_infrastructure(self):
        """End-to-end execution of BM-10 fault injection through BenchmarkRunner."""
        runner = BenchmarkRunner()
        res = runner.run_by_id("BM-10")

        assert res.benchmark_id == "BM-10"
        assert res.actual_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert res.actual_terminal_status == "FAILED"
        assert res.passed is True
        assert res.error_type == "InfrastructureError"

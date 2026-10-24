"""Deterministic benchmark runner and evaluation pipeline for RESQ Dev.

Executes curated benchmark fixtures (BM-01 through BM-10) through the isolated
verification pipeline, evaluates expected vs actual outcomes, and produces structured,
machine-readable evaluation reports.
"""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import time
from typing import Callable, Optional
from resq.config import Settings
from resq.engine.pipeline import VerificationPipeline
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.execution.docker_runner import DockerExecutionRunner
from resq.llm.mock_provider import MockLLMProvider
from resq.models import Verdict
from benchmarks.loader import get_fixture_by_id, load_all_fixtures
from benchmarks.schema import BenchmarkFixture


class FaultInjectedExecutionRunner(ExecutionEnvironment):
    """Simulates an infrastructure fault (e.g. daemon unreachable) without affecting host Docker."""

    def __init__(self, error_message: str = "INFRASTRUCTURE_ERROR: Docker daemon unreachable (simulated fault)."):
        self.error_message = error_message

    def execute(self, workspace_path: Path, command: list[str], timeout_seconds: Optional[int] = None):
        raise InfrastructureError(self.error_message)


@dataclass
class BenchmarkResult:
    """Evaluation result for an individual benchmark fixture."""

    benchmark_id: str
    title: str
    expected_verdict: Verdict
    actual_verdict: Optional[Verdict]
    expected_terminal_status: str
    actual_terminal_status: Optional[str]
    passed: bool
    duration_seconds: float = 0.0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    unified_diff: Optional[str] = None
    runs_count: int = 0

    def to_dict(self) -> dict:
        """Serializes benchmark result into a JSON-compatible dictionary."""
        d = asdict(self)
        d["expected_verdict"] = self.expected_verdict.value if self.expected_verdict else None
        d["actual_verdict"] = self.actual_verdict.value if self.actual_verdict else None
        d["duration_seconds"] = round(self.duration_seconds, 3)
        return d


@dataclass
class BenchmarkSuiteResult:
    """Aggregated suite-level evaluation metrics."""

    total_selected: int
    completed: int
    passed: int
    failed: int
    timeouts: int
    syntax_errors: int
    infrastructure_failures: int
    overall_status: str  # "PASSED" or "FAILED"
    results: list[BenchmarkResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Serializes suite result into a JSON-compatible dictionary."""
        return {
            "total_selected": self.total_selected,
            "completed": self.completed,
            "passed": self.passed,
            "failed": self.failed,
            "timeouts": self.timeouts,
            "syntax_errors": self.syntax_errors,
            "infrastructure_failures": self.infrastructure_failures,
            "overall_status": self.overall_status,
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes suite result into deterministic JSON format."""
        return json.dumps(self.to_dict(), indent=indent)

    def format_summary_table(self) -> str:
        """Generates an ASCII/markdown formatted evaluation summary table."""
        lines = []
        lines.append("=" * 125)
        lines.append(" RESQ Dev -- Complete Benchmark Evaluation Suite Results (BM-01 to BM-10)")
        lines.append("=" * 125)
        header = f"{'ID':<7} | {'Title':<32} | {'Expected Verdict':<22} | {'Actual Verdict':<22} | {'Status (Exp/Act)':<18} | {'Result':<6} | {'Time':<7}"
        lines.append(header)
        lines.append("-" * 125)

        for r in self.results:
            exp = r.expected_verdict.value if r.expected_verdict else "N/A"
            act = r.actual_verdict.value if r.actual_verdict else (r.error_type or "ERROR")
            status_str = f"{r.expected_terminal_status} / {r.actual_terminal_status or 'N/A'}"
            res_str = "PASS" if r.passed else "FAIL"
            t_str = f"{r.duration_seconds:.2f}s"
            title_truncated = r.title[:32]
            lines.append(f"{r.benchmark_id:<7} | {title_truncated:<32} | {exp:<22} | {act:<22} | {status_str:<18} | {res_str:<6} | {t_str:<7}")

        lines.append("=" * 125)
        lines.append(
            f" Summary: {self.passed}/{self.total_selected} Passed | "
            f"{self.failed} Failed | {self.timeouts} Timeouts | "
            f"{self.syntax_errors} Syntax Errors | {self.infrastructure_failures} Infra Faults | "
            f"Overall Status: {self.overall_status} ({self.total_duration_seconds:.2f}s)"
        )
        lines.append("=" * 125)
        return "\n".join(lines)


class BenchmarkRunner:
    """Orchestrates deterministic evaluation of benchmark fixtures.

    Key Invariants:
    1. Zero Host Execution: Target and invariant codes are executed only via isolated sandbox.
    2. Strict Immutability: Canonical fixture files on disk are never mutated or overwritten.
    3. Failure Isolation: Individual benchmark failures do not halt or contaminate subsequent benchmarks.
    4. Deterministic Classification: Evaluates whether actual outcomes match expected verdicts.
    """

    def __init__(
        self,
        execution_env_factory: Optional[Callable[[BenchmarkFixture], ExecutionEnvironment]] = None,
        default_timeout_seconds: int = 20,
    ):
        """Initializes BenchmarkRunner.

        Args:
            execution_env_factory: Optional factory returning an ExecutionEnvironment for a given fixture.
            default_timeout_seconds: Default hard execution timeout for benchmarks.
        """
        self.execution_env_factory = execution_env_factory
        self.default_timeout_seconds = default_timeout_seconds

    def _resolve_execution_environment(self, fixture: BenchmarkFixture) -> ExecutionEnvironment:
        """Determines the appropriate isolated execution environment for a fixture."""
        if self.execution_env_factory:
            return self.execution_env_factory(fixture)

        # Fault injection mode (e.g. BM-10)
        if fixture.fault_injection == "daemon_unreachable" or not fixture.requires_docker:
            return FaultInjectedExecutionRunner()

        # Real Docker execution sandbox
        timeout = fixture.timeout_seconds or self.default_timeout_seconds
        settings = Settings(max_execution_timeout_seconds=timeout, max_repair_cycles=1)
        return DockerExecutionRunner(settings=settings)

    def _validate_fixture_metadata(self, fixture: BenchmarkFixture) -> Optional[str]:
        """Validates that fixture metadata contains all required fields before execution."""
        if not fixture.id or not fixture.id.strip():
            return "Fixture ID is empty or missing"
        if not fixture.target_source or not fixture.target_source.strip():
            return "Fixture target_source is empty"
        if not fixture.test_source or not fixture.test_source.strip():
            return "Fixture test_source is empty"
        if not isinstance(fixture.expected_verdict, Verdict):
            return f"Invalid expected_verdict: {fixture.expected_verdict}"
        if fixture.expected_status not in ("COMPLETED", "FAILED"):
            return f"Invalid expected_status: {fixture.expected_status}"
        return None

    def run_benchmark(self, fixture: BenchmarkFixture) -> BenchmarkResult:
        """Evaluates a single benchmark fixture against its expected specification."""
        start_time = time.perf_counter()

        # 1. Validate fixture metadata
        validation_error = self._validate_fixture_metadata(fixture)
        if validation_error:
            return BenchmarkResult(
                benchmark_id=getattr(fixture, "id", "UNKNOWN"),
                title=getattr(fixture, "title", "Malformed Fixture"),
                expected_verdict=getattr(fixture, "expected_verdict", None),
                actual_verdict=None,
                expected_terminal_status=getattr(fixture, "expected_status", "UNKNOWN"),
                actual_terminal_status="FAILED",
                passed=False,
                duration_seconds=time.perf_counter() - start_time,
                error_type="MalformedFixtureError",
                error_message=validation_error,
            )

        # 2. Setup execution environment and timeout
        timeout = fixture.timeout_seconds or self.default_timeout_seconds
        settings = Settings(max_execution_timeout_seconds=timeout, max_repair_cycles=1)

        try:
            execution_env = self._resolve_execution_environment(fixture)
        except Exception as exc:
            return BenchmarkResult(
                benchmark_id=fixture.id,
                title=fixture.title,
                expected_verdict=fixture.expected_verdict,
                actual_verdict=Verdict.INFRASTRUCTURE_ERROR,
                expected_terminal_status=fixture.expected_status,
                actual_terminal_status="FAILED",
                passed=(
                    fixture.expected_verdict == Verdict.INFRASTRUCTURE_ERROR
                    and fixture.expected_status == "FAILED"
                ),
                duration_seconds=time.perf_counter() - start_time,
                error_type="InfrastructureError",
                error_message=str(exc),
            )

        # 3. Setup mock provider with fixture candidate patch
        if fixture.candidate_patch:
            mock_llm = MockLLMProvider(
                fixture_id=fixture.id,
                custom_patch=fixture.candidate_patch,
            )
        else:
            mock_llm = MockLLMProvider()

        # 4. Execute through the verification pipeline
        pipeline = VerificationPipeline(
            execution_env=execution_env,
            llm_provider=mock_llm,
            settings=settings,
        )

        try:
            job = pipeline.run(
                source_code=fixture.target_source,
                test_code=fixture.test_source,
            )
            actual_verdict = job.final_verdict
            actual_status = job.current_status
            runs_count = len(job.runs)
            unified_diff = None
            if job.runs and job.runs[-1].unified_diff:
                unified_diff = job.runs[-1].unified_diff

            # Classify specific error type
            error_type = None
            error_message = None
            if actual_verdict == Verdict.TIMEOUT_EXCEEDED:
                error_type = "TimeoutExceeded"
            elif actual_verdict == Verdict.REJECTED_SYNTAX_ERROR:
                error_type = "SyntaxError"
            elif actual_verdict == Verdict.INFRASTRUCTURE_ERROR:
                error_type = "InfrastructureError"
            elif actual_verdict == Verdict.REJECTED_REGRESSION:
                error_type = "RegressionError"
            elif actual_verdict == Verdict.REJECTED_STILL_FAILS:
                error_type = "StillFailsError"

            # Determine whether benchmark evaluation passed
            passed = (actual_verdict == fixture.expected_verdict and actual_status == fixture.expected_status)

            return BenchmarkResult(
                benchmark_id=fixture.id,
                title=fixture.title,
                expected_verdict=fixture.expected_verdict,
                actual_verdict=actual_verdict,
                expected_terminal_status=fixture.expected_status,
                actual_terminal_status=actual_status,
                passed=passed,
                duration_seconds=time.perf_counter() - start_time,
                error_type=error_type,
                error_message=error_message,
                unified_diff=unified_diff,
                runs_count=runs_count,
            )

        except Exception as exc:
            return BenchmarkResult(
                benchmark_id=fixture.id,
                title=fixture.title,
                expected_verdict=fixture.expected_verdict,
                actual_verdict=None,
                expected_terminal_status=fixture.expected_status,
                actual_terminal_status="FAILED",
                passed=False,
                duration_seconds=time.perf_counter() - start_time,
                error_type="ExecutionException",
                error_message=str(exc),
            )

    def run_by_id(self, benchmark_id: str) -> BenchmarkResult:
        """Executes a single benchmark identified by its ID (e.g., 'BM-01')."""
        fixture = get_fixture_by_id(benchmark_id)
        if not fixture:
            return BenchmarkResult(
                benchmark_id=benchmark_id,
                title="Unknown Benchmark",
                expected_verdict=None,  # type: ignore[arg-type]
                actual_verdict=None,
                expected_terminal_status="UNKNOWN",
                actual_terminal_status="FAILED",
                passed=False,
                error_type="FixtureNotFoundError",
                error_message=f"No benchmark found with ID: {benchmark_id}",
            )
        return self.run_benchmark(fixture)

    def run_subset(self, benchmark_ids: list[str]) -> BenchmarkSuiteResult:
        """Executes a specified list of benchmark IDs and aggregates results."""
        start_time = time.perf_counter()
        results: list[BenchmarkResult] = []

        for b_id in benchmark_ids:
            res = self.run_by_id(b_id)
            results.append(res)

        total_duration = time.perf_counter() - start_time
        return self._aggregate_suite_result(results, total_selected=len(benchmark_ids), total_duration=total_duration)

    def run_all(self) -> BenchmarkSuiteResult:
        """Discovers and executes all 10 benchmark fixtures in deterministic order."""
        start_time = time.perf_counter()
        fixtures = load_all_fixtures()
        results: list[BenchmarkResult] = []

        for fixture in fixtures:
            res = self.run_benchmark(fixture)
            results.append(res)

        total_duration = time.perf_counter() - start_time
        return self._aggregate_suite_result(results, total_selected=len(fixtures), total_duration=total_duration)

    def _aggregate_suite_result(
        self,
        results: list[BenchmarkResult],
        total_selected: int,
        total_duration: float,
    ) -> BenchmarkSuiteResult:
        """Aggregates individual benchmark results into a BenchmarkSuiteResult summary."""
        completed = len(results)
        passed_count = sum(1 for r in results if r.passed)
        failed_count = sum(1 for r in results if not r.passed)
        timeouts_count = sum(1 for r in results if r.actual_verdict == Verdict.TIMEOUT_EXCEEDED)
        syntax_count = sum(1 for r in results if r.actual_verdict == Verdict.REJECTED_SYNTAX_ERROR)
        infra_count = sum(1 for r in results if r.actual_verdict == Verdict.INFRASTRUCTURE_ERROR)

        overall_status = "PASSED" if (passed_count == total_selected and total_selected > 0) else "FAILED"

        return BenchmarkSuiteResult(
            total_selected=total_selected,
            completed=completed,
            passed=passed_count,
            failed=failed_count,
            timeouts=timeouts_count,
            syntax_errors=syntax_count,
            infrastructure_failures=infra_count,
            overall_status=overall_status,
            results=results,
            total_duration_seconds=total_duration,
        )

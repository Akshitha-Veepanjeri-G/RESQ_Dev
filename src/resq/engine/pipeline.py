"""Core verification pipeline orchestrating failure capture, patch application, and isolated verification."""

import shutil
import tempfile
from pathlib import Path
from typing import Optional
from resq.config import Settings, get_settings
from resq.engine.failure_analyzer import FailureAnalyzer
from resq.engine.patch_applier import PatchApplier
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.llm.base import LLMProvider
from resq.llm.factory import get_llm_provider
from resq.models import (
    CandidatePatch,
    ExecutionResult,
    FailureArtifact,
    Verdict,
    VerificationJob,
    VerificationRun,
)


class VerificationPipeline:
    """Orchestrates the deterministic verification and patch evaluation loop.

    Key Invariants:
    1. Deterministic Truth Gate: Verdict is VERIFIED only if re-verification exits 0 in Docker.
    2. Original Source Immutability: Candidate patches are applied only to temporary workspaces.
    3. Mandatory Sandboxing: All execution delegates to the ExecutionEnvironment (Docker).
    4. Bounded Repair Cycles: Bounded by max_repair_cycles (default 1, max 2).
    """

    def __init__(
        self,
        execution_env: ExecutionEnvironment,
        llm_provider: Optional[LLMProvider] = None,
        settings: Optional[Settings] = None,
        failure_analyzer: Optional[FailureAnalyzer] = None,
        patch_applier: Optional[PatchApplier] = None,
    ):
        self.settings = settings or get_settings()
        self.execution_env = execution_env
        self.llm_provider = llm_provider or get_llm_provider(self.settings)
        self.failure_analyzer = failure_analyzer or FailureAnalyzer()
        self.patch_applier = patch_applier or PatchApplier()

    def run(
        self,
        source_code: str,
        test_code: str,
        target_filename: str = "target.py",
        test_filename: str = "test_target.py",
    ) -> VerificationJob:
        """Executes the verification pipeline.

        Args:
            source_code: The Python module to verify.
            test_code: The test harness containing baseline unit tests and Hypothesis properties.
            target_filename: Name of the target source file (default: target.py).
            test_filename: Name of the test suite file (default: test_target.py).

        Returns:
            A completed VerificationJob entity with execution runs and final verdict.
        """
        job = VerificationJob(
            target_filename=target_filename,
            source_code=source_code,
            invariants_code=test_code,
            current_status="RUNNING_BASELINE",
        )

        baseline_temp_dir = Path(tempfile.mkdtemp(prefix="resq_job_base_"))

        try:
            # 1. Setup baseline temporary workspace
            target_path = baseline_temp_dir / target_filename
            test_path = baseline_temp_dir / test_filename
            target_path.write_text(source_code, encoding="utf-8")
            test_path.write_text(test_code, encoding="utf-8")

            # 2. Execute baseline tests inside Docker sandbox
            try:
                baseline_result = self.execution_env.execute(
                    baseline_temp_dir,
                    ["pytest", test_filename, "--tb=short", "-q", "-o", "cache_dir=/tmp/.pytest_cache"],
                )
            except InfrastructureError as exc:
                infra_result = ExecutionResult(
                    exit_code=125,
                    stdout="",
                    stderr=str(exc),
                    timed_out=False,
                    duration_seconds=0.0,
                )
                baseline_run = VerificationRun(
                    job_id=job.id,
                    run_type="BASELINE",
                    cycle_index=0,
                    execution_result=infra_result,
                    verdict=Verdict.INFRASTRUCTURE_ERROR,
                )
                job.runs.append(baseline_run)
                job.final_verdict = Verdict.INFRASTRUCTURE_ERROR
                job.current_status = "FAILED"
                return job

            # Check if baseline completed cleanly without any failure
            if baseline_result.exit_code == 0:
                baseline_run = VerificationRun(
                    job_id=job.id,
                    run_type="BASELINE",
                    cycle_index=0,
                    execution_result=baseline_result,
                    verdict=Verdict.NO_FAILURE_FOUND,
                )
                job.runs.append(baseline_run)
                job.final_verdict = Verdict.NO_FAILURE_FOUND
                job.current_status = "COMPLETED"
                return job

            # Check for infrastructure or timeout failures during baseline
            if baseline_result.timed_out:
                baseline_run = VerificationRun(
                    job_id=job.id,
                    run_type="BASELINE",
                    cycle_index=0,
                    execution_result=baseline_result,
                    verdict=Verdict.TIMEOUT_EXCEEDED,
                )
                job.runs.append(baseline_run)
                job.final_verdict = Verdict.TIMEOUT_EXCEEDED
                job.current_status = "FAILED"
                return job

            if baseline_result.exit_code == 125:
                baseline_run = VerificationRun(
                    job_id=job.id,
                    run_type="BASELINE",
                    cycle_index=0,
                    execution_result=baseline_result,
                    verdict=Verdict.INFRASTRUCTURE_ERROR,
                )
                job.runs.append(baseline_run)
                job.final_verdict = Verdict.INFRASTRUCTURE_ERROR
                job.current_status = "FAILED"
                return job

            # 3. Analyze failure evidence
            failure_artifact = self.failure_analyzer.analyze(baseline_result)
            if not failure_artifact.is_reproducible:
                baseline_run = VerificationRun(
                    job_id=job.id,
                    run_type="BASELINE",
                    cycle_index=0,
                    execution_result=baseline_result,
                    failure_artifact=failure_artifact,
                    verdict=Verdict.INSUFFICIENT_EVIDENCE,
                )
                job.runs.append(baseline_run)
                job.final_verdict = Verdict.INSUFFICIENT_EVIDENCE
                job.current_status = "FAILED"
                return job

            baseline_run = VerificationRun(
                job_id=job.id,
                run_type="BASELINE",
                cycle_index=0,
                execution_result=baseline_result,
                failure_artifact=failure_artifact,
                verdict=Verdict.REJECTED_STILL_FAILS,  # Unpatched baseline failed as expected
            )
            job.runs.append(baseline_run)

            # 4. Bounded repair loop
            max_cycles = min(self.settings.max_repair_cycles, 2)
            current_failure = failure_artifact

            for cycle in range(1, max_cycles + 1):
                job.current_status = f"REPAIR_CYCLE_{cycle}"

                # Request candidate patch from LLM Gateway
                try:
                    candidate_patch = self.llm_provider.generate_patch(source_code, current_failure)
                except Exception as exc:
                    err_run = VerificationRun(
                        job_id=job.id,
                        run_type="REVERIFICATION",
                        cycle_index=cycle,
                        verdict=Verdict.LLM_ERROR,
                    )
                    job.runs.append(err_run)
                    job.final_verdict = Verdict.LLM_ERROR
                    job.current_status = "FAILED"
                    return job

                # Static AST syntax gate
                is_valid_syntax, syntax_error = self.patch_applier.validate_syntax(candidate_patch.patch_code)
                if not is_valid_syntax:
                    syntax_run = VerificationRun(
                        job_id=job.id,
                        run_type="REVERIFICATION",
                        cycle_index=cycle,
                        candidate_patch=candidate_patch,
                        verdict=Verdict.REJECTED_SYNTAX_ERROR,
                    )
                    job.runs.append(syntax_run)
                    if cycle >= max_cycles:
                        job.final_verdict = Verdict.REJECTED_SYNTAX_ERROR
                        job.current_status = "COMPLETED"
                        return job
                    continue

                # Apply candidate patch to an isolated temporary copy
                patch_temp_dir: Optional[Path] = None
                try:
                    patch_temp_dir, unified_diff = self.patch_applier.prepare_patch_workspace(
                        baseline_temp_dir,
                        candidate_patch.patch_code,
                        target_filename=target_filename,
                    )

                    # Re-verify inside Docker sandbox
                    try:
                        reverify_result = self.execution_env.execute(
                            patch_temp_dir,
                            ["pytest", test_filename, "--tb=short", "-q", "-o", "cache_dir=/tmp/.pytest_cache"],
                        )
                    except InfrastructureError as exc:
                        infra_result = ExecutionResult(
                            exit_code=125,
                            stdout="",
                            stderr=str(exc),
                            timed_out=False,
                            duration_seconds=0.0,
                        )
                        cycle_run = VerificationRun(
                            job_id=job.id,
                            run_type="REVERIFICATION",
                            cycle_index=cycle,
                            execution_result=infra_result,
                            candidate_patch=candidate_patch,
                            unified_diff=unified_diff,
                            verdict=Verdict.INFRASTRUCTURE_ERROR,
                        )
                        job.runs.append(cycle_run)
                        job.final_verdict = Verdict.INFRASTRUCTURE_ERROR
                        job.current_status = "FAILED"
                        return job

                    # Determine re-verification verdict
                    if reverify_result.timed_out:
                        cycle_verdict = Verdict.TIMEOUT_EXCEEDED
                    elif reverify_result.exit_code == 125:
                        cycle_verdict = Verdict.INFRASTRUCTURE_ERROR
                    elif reverify_result.exit_code == 0:
                        cycle_verdict = Verdict.VERIFIED
                    else:
                        # Distinguish regression vs un-resolved reproducer
                        combined_out = f"{reverify_result.stdout}\n{reverify_result.stderr}".lower()
                        if "baseline" in combined_out or "regression" in combined_out:
                            cycle_verdict = Verdict.REJECTED_REGRESSION
                        else:
                            cycle_verdict = Verdict.REJECTED_STILL_FAILS

                    cycle_run = VerificationRun(
                        job_id=job.id,
                        run_type="REVERIFICATION",
                        cycle_index=cycle,
                        execution_result=reverify_result,
                        candidate_patch=candidate_patch,
                        unified_diff=unified_diff,
                        verdict=cycle_verdict,
                    )
                    job.runs.append(cycle_run)

                    if cycle_verdict == Verdict.VERIFIED:
                        job.final_verdict = Verdict.VERIFIED
                        job.current_status = "COMPLETED"
                        return job

                    # Terminal failure if timeout or infrastructure failure occurred during reverification
                    if cycle_verdict in (Verdict.TIMEOUT_EXCEEDED, Verdict.INFRASTRUCTURE_ERROR):
                        job.final_verdict = cycle_verdict
                        job.current_status = "FAILED"
                        return job

                    # Update failure context for next cycle if budget remains
                    current_failure = self.failure_analyzer.analyze(reverify_result)

                    if cycle >= max_cycles:
                        job.final_verdict = cycle_verdict
                        job.current_status = "COMPLETED"
                        return job

                finally:
                    if patch_temp_dir and patch_temp_dir.exists():
                        shutil.rmtree(patch_temp_dir, ignore_errors=True)

        finally:
            if baseline_temp_dir.exists():
                shutil.rmtree(baseline_temp_dir, ignore_errors=True)

        return job

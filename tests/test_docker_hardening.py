"""Focused unit and hardening tests for DockerExecutionRunner, stream bounding, and pipeline infrastructure errors."""

import hashlib
import io
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from resq.config import Settings
from resq.engine.pipeline import VerificationPipeline
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.execution.docker_runner import DockerExecutionRunner, _drain_stream_to_bounded_file
from resq.llm.mock_provider import MockLLMProvider
from resq.models import ExecutionResult, FailureArtifact, Verdict


class MockPipeStream(io.BytesIO):
    """Simulates a subprocess pipe stream."""
    def read(self, n=-1):
        return super().read(n)


class TestDockerExecutionRunnerHardening:
    """Verifies Docker runner exception classification, cleanup behavior, and output bounding."""

    def test_docker_daemon_unavailable_raises_infrastructure_error(self, tmp_path):
        runner = DockerExecutionRunner()
        with patch.object(runner, "_is_docker_available", return_value=False):
            with pytest.raises(InfrastructureError) as exc_info:
                runner.execute(tmp_path, ["python", "-c", "pass"])
            assert "INFRASTRUCTURE_ERROR" in str(exc_info.value)
            assert issubclass(InfrastructureError, RuntimeError)

    def test_bounded_output_streaming_truncates_large_stdout(self, tmp_path):
        """Verifies output stream bounding discards excess bytes without memory or disk exhaustion."""
        target_file = tmp_path / "stdout.bin"
        max_bytes = 1024
        large_payload = b"A" * (100 * 1024)  # 100 KiB
        stream = io.BytesIO(large_payload)
        holder = {}

        _drain_stream_to_bounded_file(stream, target_file, max_bytes, "stdout", holder)

        assert holder.get("stdout_truncated") is True
        assert holder.get("stdout_bytes_written") == max_bytes
        assert holder.get("stdout_bytes_discarded") == len(large_payload) - max_bytes

        content = target_file.read_text(encoding="utf-8")
        assert content.startswith("A" * max_bytes)
        assert "[... stdout truncated at 1024 bytes" in content
        assert "additional bytes discarded" in content
        # Ensure final file size is bounded (max_bytes + length of truncation marker ~1100 bytes)
        assert len(content) < 1200

    def test_cleanup_attempted_on_normal_exit(self, tmp_path):
        runner = DockerExecutionRunner()
        with patch.object(runner, "_is_docker_available", return_value=True), \
             patch("subprocess.Popen") as mock_popen, \
             patch.object(runner, "_safe_docker_cleanup") as mock_cleanup:
            mock_proc = MagicMock()
            mock_proc.wait.return_value = 0
            mock_proc.stdout = io.BytesIO(b"OK")
            mock_proc.stderr = io.BytesIO(b"")
            mock_popen.return_value = mock_proc

            res = runner.execute(tmp_path, ["pytest"])
            assert res.exit_code == 0
            # Cleanup container via rm must be called in finally
            mock_cleanup.assert_called_with(mock_cleanup.call_args[0][0], action="rm")

    def test_cleanup_attempted_on_timeout(self, tmp_path):
        runner = DockerExecutionRunner()
        with patch.object(runner, "_is_docker_available", return_value=True), \
             patch("subprocess.Popen") as mock_popen, \
             patch.object(runner, "_safe_docker_cleanup") as mock_cleanup:
            mock_proc = MagicMock()
            mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd=["docker"], timeout=2)
            mock_proc.stdout = io.BytesIO(b"")
            mock_proc.stderr = io.BytesIO(b"")
            mock_popen.return_value = mock_proc

            res = runner.execute(tmp_path, ["pytest"], timeout_seconds=2)
            assert res.timed_out is True
            assert res.exit_code == 124

            # Must attempt kill on timeout, and rm in finally
            actions = [call[1].get("action") for call in mock_cleanup.call_args_list]
            assert "kill" in actions
            assert "rm" in actions

    def test_cleanup_failure_does_not_mask_primary_result(self, tmp_path):
        runner = DockerExecutionRunner()
        with patch.object(runner, "_is_docker_available", return_value=True), \
             patch("subprocess.Popen") as mock_popen, \
             patch("subprocess.run", side_effect=RuntimeError("Docker daemon crashed during cleanup")):
            mock_proc = MagicMock()
            mock_proc.wait.return_value = 0
            mock_proc.stdout = io.BytesIO(b"ALL_TESTS_PASSED")
            mock_proc.stderr = io.BytesIO(b"")
            mock_popen.return_value = mock_proc

            # Must return primary result cleanly without raising the cleanup exception
            res = runner.execute(tmp_path, ["pytest"])
            assert res.exit_code == 0
            assert "ALL_TESTS_PASSED" in res.stdout

    def test_launch_failure_raises_infrastructure_error(self, tmp_path):
        runner = DockerExecutionRunner()
        with patch.object(runner, "_is_docker_available", return_value=True), \
             patch("subprocess.Popen", side_effect=FileNotFoundError("docker executable not found")):
            with pytest.raises(InfrastructureError) as exc_info:
                runner.execute(tmp_path, ["pytest"])
            assert "INFRASTRUCTURE_ERROR" in str(exc_info.value)


class MockFailingExecutionEnvironment(ExecutionEnvironment):
    """Configurable execution environment for pipeline error simulation."""

    def __init__(self, baseline_result=None, reverify_result=None, raise_on_baseline=None, raise_on_reverify=None):
        self.baseline_result = baseline_result
        self.reverify_result = reverify_result
        self.raise_on_baseline = raise_on_baseline
        self.raise_on_reverify = raise_on_reverify
        self.call_count = 0

    def execute(self, workspace_path, command, timeout_seconds=None):
        self.call_count += 1
        if self.call_count == 1:
            if self.raise_on_baseline:
                raise self.raise_on_baseline
            return self.baseline_result
        else:
            if self.raise_on_reverify:
                raise self.raise_on_reverify
            return self.reverify_result


class TestPipelineInfrastructureHandling:
    """Verifies that the verification pipeline returns terminal FAILED jobs on infrastructure failures."""

    SOURCE_CODE = "def add(a, b): return a - b\n"
    TEST_CODE = "from target import add\ndef test_add(): assert add(1, 2) == 3\n"

    def test_pipeline_catches_baseline_infrastructure_error(self):
        env = MockFailingExecutionEnvironment(
            raise_on_baseline=InfrastructureError("Docker daemon is unreachable.")
        )
        pipeline = VerificationPipeline(execution_env=env)

        job = pipeline.run(self.SOURCE_CODE, self.TEST_CODE)
        assert job.current_status == "FAILED"
        assert job.final_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert len(job.runs) == 1
        assert job.runs[0].verdict == Verdict.INFRASTRUCTURE_ERROR
        assert "Docker daemon is unreachable" in job.runs[0].execution_result.stderr

    def test_pipeline_handles_exit_code_125_on_baseline(self):
        env = MockFailingExecutionEnvironment(
            baseline_result=ExecutionResult(
                exit_code=125,
                stdout="",
                stderr="docker: Error response from daemon: repository not found",
            )
        )
        pipeline = VerificationPipeline(execution_env=env)

        job = pipeline.run(self.SOURCE_CODE, self.TEST_CODE)
        assert job.current_status == "FAILED"
        assert job.final_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert len(job.runs) == 1
        assert job.runs[0].verdict == Verdict.INFRASTRUCTURE_ERROR

    def test_pipeline_catches_reverification_infrastructure_error(self):
        # Baseline fails with reproducible failure
        baseline = ExecutionResult(
            exit_code=1,
            stdout="E       AssertionError: assert -1 == 3\nFalsifying example: test_add()",
            stderr="",
        )
        env = MockFailingExecutionEnvironment(
            baseline_result=baseline,
            raise_on_reverify=InfrastructureError("Container launch failed: out of disk space"),
        )
        mock_llm = MockLLMProvider(mode="valid")
        pipeline = VerificationPipeline(execution_env=env, llm_provider=mock_llm)

        job = pipeline.run(self.SOURCE_CODE, self.TEST_CODE)
        assert job.current_status == "FAILED"
        assert job.final_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert len(job.runs) == 2
        assert job.runs[1].verdict == Verdict.INFRASTRUCTURE_ERROR
        assert job.final_verdict != Verdict.VERIFIED

    def test_pipeline_handles_reverification_exit_code_125(self):
        baseline = ExecutionResult(
            exit_code=1,
            stdout="E       AssertionError: assert -1 == 3\nFalsifying example: test_add()",
            stderr="",
        )
        reverify = ExecutionResult(
            exit_code=125,
            stdout="",
            stderr="docker: container runtime error",
        )
        env = MockFailingExecutionEnvironment(
            baseline_result=baseline,
            reverify_result=reverify,
        )
        mock_llm = MockLLMProvider(mode="valid")
        pipeline = VerificationPipeline(execution_env=env, llm_provider=mock_llm)

        job = pipeline.run(self.SOURCE_CODE, self.TEST_CODE)
        assert job.current_status == "FAILED"
        assert job.final_verdict == Verdict.INFRASTRUCTURE_ERROR
        assert job.runs[1].verdict == Verdict.INFRASTRUCTURE_ERROR
        assert job.final_verdict != Verdict.VERIFIED

    def test_timeout_remains_distinct_from_infrastructure_error(self):
        # Baseline timeout
        env_base_timeout = MockFailingExecutionEnvironment(
            baseline_result=ExecutionResult(
                exit_code=124,
                stdout="",
                stderr="TIMEOUT_EXCEEDED: Container exceeded hard timeout of 10s.",
                timed_out=True,
            )
        )
        pipeline = VerificationPipeline(execution_env=env_base_timeout)
        job = pipeline.run(self.SOURCE_CODE, self.TEST_CODE)
        assert job.final_verdict == Verdict.TIMEOUT_EXCEEDED
        assert job.current_status == "FAILED"

        # Re-verification timeout
        baseline_fail = ExecutionResult(
            exit_code=1,
            stdout="E       AssertionError: assert -1 == 3\nFalsifying example: test_add()",
            stderr="",
        )
        reverify_timeout = ExecutionResult(
            exit_code=124,
            stdout="",
            stderr="TIMEOUT_EXCEEDED: Container exceeded hard timeout of 10s.",
            timed_out=True,
        )
        env_reverify_timeout = MockFailingExecutionEnvironment(
            baseline_result=baseline_fail,
            reverify_result=reverify_timeout,
        )
        pipeline2 = VerificationPipeline(execution_env=env_reverify_timeout, llm_provider=MockLLMProvider(mode="valid"))
        job2 = pipeline2.run(self.SOURCE_CODE, self.TEST_CODE)
        assert job2.final_verdict == Verdict.TIMEOUT_EXCEEDED
        assert job2.current_status == "FAILED"
        assert job2.final_verdict != Verdict.INFRASTRUCTURE_ERROR

    def test_original_source_files_immutability_under_infrastructure_failure(self, tmp_path):
        source_file = tmp_path / "solution.py"
        source_content = "def binary_search(arr, target): return -1\n"
        source_file.write_text(source_content, encoding="utf-8")
        initial_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()

        env = MockFailingExecutionEnvironment(
            raise_on_baseline=InfrastructureError("Docker daemon crashed.")
        )
        pipeline = VerificationPipeline(execution_env=env)
        pipeline.run(source_content, self.TEST_CODE)

        current_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
        assert current_hash == initial_hash, "Original source file was mutated during infrastructure error!"

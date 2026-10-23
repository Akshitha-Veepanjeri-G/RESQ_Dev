"""Integration tests for DockerExecutionRunner verifying sandboxing and isolation boundaries."""

import subprocess
import pytest
from resq.execution.docker_runner import DockerExecutionRunner


class TestDockerExecutionRunner:
    """Verifies Docker execution security boundaries, network isolation, and timeouts."""

    @pytest.fixture(autouse=True)
    def ensure_docker_daemon(self):
        """Skip if Docker daemon is unreachable."""
        runner = DockerExecutionRunner()
        if not runner._is_docker_available():
            pytest.skip("Docker daemon is not reachable.")

    def test_basic_execution_in_sandbox(self, tmp_path):
        runner = DockerExecutionRunner()
        result = runner.execute(
            workspace_path=tmp_path,
            command=["python", "-c", "print('RESQ_SANDBOX_OK')"],
            timeout_seconds=10,
        )
        assert result.exit_code == 0
        assert "RESQ_SANDBOX_OK" in result.stdout
        assert result.timed_out is False
        assert result.duration_seconds > 0

    def test_network_isolation_denies_sockets(self, tmp_path):
        """Verifies that --network none blocks outbound socket creation."""
        network_test_code = (
            "import socket\n"
            "try:\n"
            "    s = socket.create_connection(('8.8.8.8', 53), timeout=1)\n"
            "    print('CONNECTED_UNEXPECTEDLY')\n"
            "except OSError as e:\n"
            "    print(f'NETWORK_DENIED: {type(e).__name__}')\n"
        )
        runner = DockerExecutionRunner()
        result = runner.execute(
            workspace_path=tmp_path,
            command=["python", "-c", network_test_code],
            timeout_seconds=10,
        )
        assert result.exit_code == 0
        assert "NETWORK_DENIED" in result.stdout
        assert "CONNECTED_UNEXPECTEDLY" not in result.stdout

    def test_non_root_execution(self, tmp_path):
        """Verifies that execution runs as unprivileged UID 10001."""
        runner = DockerExecutionRunner()
        result = runner.execute(
            workspace_path=tmp_path,
            command=["id"],
            timeout_seconds=10,
        )
        assert result.exit_code == 0
        assert "uid=10001(resquser)" in result.stdout

    def test_timeout_enforcement_and_container_cleanup(self, tmp_path):
        """Verifies that the host runner terminates runaway processes and cleans up containers."""
        runner = DockerExecutionRunner()
        result = runner.execute(
            workspace_path=tmp_path,
            command=["python", "-c", "import time; time.sleep(15)"],
            timeout_seconds=2,
        )
        assert result.timed_out is True
        assert result.exit_code == 124
        assert "TIMEOUT_EXCEEDED" in result.stderr

        # Verify no orphaned containers remain running
        ps_out = subprocess.run(
            ["docker", "ps", "--filter", "name=resq_run_", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )
        assert ps_out.stdout.strip() == "", "Found orphaned container lingering after timeout!"

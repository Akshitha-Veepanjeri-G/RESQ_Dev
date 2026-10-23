"""Docker-based execution runner enforcing strict sandboxing, output bounding, and resource limits."""

import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Optional
import uuid
from resq.config import Settings, get_settings
from resq.execution.base import ExecutionEnvironment, InfrastructureError
from resq.models import ExecutionResult


def _drain_stream_to_bounded_file(
    stream,
    temp_path: Path,
    max_bytes: int,
    stream_name: str,
    holder: dict,
) -> None:
    """Reads raw bytes from stream, writing at most max_bytes to temp_path.

    Subsequent bytes are discarded to prevent memory or disk exhaustion.
    Guarantees pipe is drained so subprocess does not block on full OS pipe buffer.
    """
    total_written = 0
    total_discarded = 0
    try:
        with open(temp_path, "wb") as f:
            while True:
                try:
                    chunk = stream.read(8192)
                except (OSError, ValueError):
                    break
                if not chunk:
                    break
                if total_written < max_bytes:
                    allowed = max_bytes - total_written
                    to_write = chunk[:allowed]
                    f.write(to_write)
                    total_written += len(to_write)
                    remaining_discarded = len(chunk) - len(to_write)
                    if remaining_discarded > 0:
                        total_discarded += remaining_discarded
                else:
                    total_discarded += len(chunk)

            if total_discarded > 0:
                marker = (
                    f"\n[... {stream_name} truncated at {max_bytes} bytes "
                    f"({total_discarded} additional bytes discarded) ...]\n"
                ).encode("utf-8", errors="replace")
                f.write(marker)
    except Exception as exc:
        holder[f"{stream_name}_error"] = str(exc)
    finally:
        try:
            stream.close()
        except Exception:
            pass
        holder[f"{stream_name}_truncated"] = (total_discarded > 0)
        holder[f"{stream_name}_bytes_written"] = total_written
        holder[f"{stream_name}_bytes_discarded"] = total_discarded


class DockerExecutionRunner(ExecutionEnvironment):
    """Executes untrusted code inside an isolated, resource-constrained Docker container.

    Security Boundaries:
    - --network none: Absolute network isolation (no socket creation or data exfiltration).
    - --memory / --memory-swap: Hard physical memory limits (prevents RAM exhaustion).
    - --cpus: CPU quota allocation (prevents CPU starvation).
    - --pids-limit: Process limit (prevents fork bombs).
    - --read-only: Root filesystem is read-only.
    - --tmpfs /tmp: Writable tempfs capped at 64m with noexec,nosuid.
    - --user 10001:10001: Unprivileged user (resquser).
    - --cap-drop ALL: Drops all Linux kernel capabilities.
    - Host-side timeout: Host enforces hard execution deadline and terminates container.
    - Output Bounding: Streams process output to bounded temporary files (max 64 KiB),
      preventing in-memory heap explosion on runaway logging.
    - Bounded Cleanup: Cleanup commands have strict timeouts and never overwrite primary results.
    - Zero host fallback: Untrusted code is NEVER executed on the host system.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def _is_docker_available(self) -> bool:
        """Verifies that Docker daemon is running and responsive."""
        try:
            res = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0 and bool(res.stdout.strip())
        except Exception:
            return False

    def _safe_docker_cleanup(self, container_name: str, action: str = "rm") -> None:
        """Safely cleans up a container with a short bounded timeout, never raising.

        Guarantees that cleanup command timeouts or failures cannot mask the
        primary execution result or raise unexpected secondary errors.
        """
        cmd = (
            ["docker", "rm", "-f", container_name]
            if action == "rm"
            else ["docker", "kill", container_name]
        )
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=5,
            )
        except Exception:
            # Cleanup failure must never mask primary execution result
            pass

    def execute(
        self,
        workspace_path: Path,
        command: list[str],
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        """Runs the specified command inside an ephemeral sandboxed Docker container."""
        if not self._is_docker_available():
            raise InfrastructureError(
                "INFRASTRUCTURE_ERROR: Docker daemon is unavailable or unreachable. "
                "Executing untrusted code on the host without sandboxing is strictly prohibited."
            )

        resolved_workspace = workspace_path.resolve()
        timeout = timeout_seconds or self.settings.max_execution_timeout_seconds
        container_name = f"resq_run_{uuid.uuid4().hex[:12]}"
        max_output_bytes = getattr(self.settings, "docker_max_output_bytes", 65_536)

        docker_cmd = [
            "docker",
            "run",
            "--name",
            container_name,
            "--rm",
            "--network",
            "none",
            "--memory",
            self.settings.docker_memory_limit,
            "--memory-swap",
            self.settings.docker_memory_limit,
            "--cpus",
            str(self.settings.docker_cpu_limit),
            "--pids-limit",
            str(self.settings.docker_pids_limit),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--volume",
            f"{resolved_workspace}:/workspace:rw",
            "--workdir",
            "/workspace",
            self.settings.docker_image_name,
        ] + command

        start_time = time.perf_counter()
        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = 1

        stdout_temp: Optional[Path] = None
        stderr_temp: Optional[Path] = None
        stream_holder: dict = {}

        try:
            # Create temporary files for bounded streaming
            stdout_fd, stdout_temp_str = tempfile.mkstemp(prefix="resq_stdout_")
            stderr_fd, stderr_temp_str = tempfile.mkstemp(prefix="resq_stderr_")
            os.close(stdout_fd)
            os.close(stderr_fd)
            stdout_temp = Path(stdout_temp_str)
            stderr_temp = Path(stderr_temp_str)

            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )

            # Spawn reader threads for bounded streaming to disk
            t_out = threading.Thread(
                target=_drain_stream_to_bounded_file,
                args=(process.stdout, stdout_temp, max_output_bytes, "stdout", stream_holder),
                daemon=True,
            )
            t_err = threading.Thread(
                target=_drain_stream_to_bounded_file,
                args=(process.stderr, stderr_temp, max_output_bytes, "stderr", stream_holder),
                daemon=True,
            )
            t_out.start()
            t_err.start()

            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
                # Bounded force-kill of container
                self._safe_docker_cleanup(container_name, action="kill")
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

            # Wait for reader threads to complete draining pipes
            t_out.join(timeout=3)
            t_err.join(timeout=3)

            # Read bounded output from temporary files
            if stdout_temp and stdout_temp.exists():
                stdout = stdout_temp.read_text(encoding="utf-8", errors="replace")
            if stderr_temp and stderr_temp.exists():
                stderr = stderr_temp.read_text(encoding="utf-8", errors="replace")

            if timed_out:
                stderr = (
                    f"TIMEOUT_EXCEEDED: Container exceeded hard timeout of {timeout}s.\n"
                    + stderr
                )

        except FileNotFoundError as exc:
            exit_code = 125
            stderr = f"INFRASTRUCTURE_ERROR: Docker CLI not found: {exc}"
            raise InfrastructureError(stderr) from exc
        except Exception as exc:
            exit_code = 125
            stderr = f"INFRASTRUCTURE_ERROR: Failed to run Docker command: {exc}"
            raise InfrastructureError(stderr) from exc
        finally:
            duration = time.perf_counter() - start_time
            # Ensure container is purged even if --rm fails on abrupt termination
            self._safe_docker_cleanup(container_name, action="rm")
            # Always clean up temporary output files
            if stdout_temp and stdout_temp.exists():
                try:
                    stdout_temp.unlink(missing_ok=True)
                except Exception:
                    pass
            if stderr_temp and stderr_temp.exists():
                try:
                    stderr_temp.unlink(missing_ok=True)
                except Exception:
                    pass

        return ExecutionResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_seconds=round(duration, 3),
        )

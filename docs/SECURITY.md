# RESQ Dev — Security Model & Sandbox Architecture

> **Threat Model, Sandboxing Constraints & Risk Analysis**  
> Status: Authoritative Security Reference  
> Parent Document: [PROJECT_CONTEXT.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/PROJECT_CONTEXT.md)

---

## 1. Threat Model & Adversarial Assumptions

RESQ Dev ingests user-supplied Python modules and generates automated code patches via an LLM. Both sources must be treated as **untrusted, potentially hostile input**.

### 1.1 Threat Vectors

| Threat Vector | Mechanism / Attack Scenario | Potential Impact |
| :--- | :--- | :--- |
| **Filesystem Traversal / Destruction** | Code attempts `os.walk('/')`, `shutil.rmtree()`, or overwriting `.env` and host project files. | Data destruction, source code corruption, exfiltration of host secrets. |
| **Process Hijacking / Shell Execution** | Code issues `subprocess.Popen('/bin/sh')`, `os.system('curl ...')`, or executes downloaded binaries. | Host compromise, remote code execution (RCE). |
| **Network Exfiltration / Ingress** | Code opens sockets, contacts command-and-control servers, or downloads second-stage payloads. | Data exfiltration, credential leakage, botnet participation. |
| **Denial of Service (DoS) / Resource Exhaustion** | Code spawns infinite loops (`while True:`), memory bombs (`bytearray(10**10)`), or fork bombs (`os.fork()`). | Host CPU/RAM starvation, system hang, developer workspace freeze. |
| **Prompt Injection / Invariant Corruption** | Malicious comments or data in user code trick the LLM into generating patches that delete test assertions or hardcode trivial `return True`. | False verification, compromised test integrity. |

---

## 2. Sandboxing Strategy & Boundary Definition

### 2.1 Why Process-Level Subprocesses on Windows Fail
On a Windows host machine, executing code via `subprocess.run(["python", ...])` — even in a temporary directory with a timeout — **is not a security boundary**:
1. The process executes with the full user privileges of the logged-in Windows account.
2. It can read, modify, or delete any file in the workspace or user directory.
3. It has unrestricted access to the local loopback and outbound internet networks.
4. Windows process trees do not reliably terminate on child exit unless managed via Windows Job Objects.

**Architectural Rule:** RESQ Dev **never** executes untrusted user code or candidate patches in an unsandboxed local host process. If Docker is unavailable, execution fails with `INFRASTRUCTURE_ERROR`.

---

## 3. Docker Sandbox Security Design

### 3.1 Container Containment Flags
All untrusted code and generated patches execute within an ephemeral Docker container using `resq-sandbox:latest`:

```bash
docker run --rm \
  --name "resq_run_<uuid>" \
  --network none \
  --memory 512m \
  --memory-swap 512m \
  --cpus 1.0 \
  --pids-limit 64 \
  --read-only \
  --user 10001:10001 \
  --cap-drop ALL \
  --stop-timeout 5 \
  --volume "<specific_job_temp_dir>:/workspace:rw" \
  --workdir /workspace \
  resq-sandbox:latest \
  pytest --tb=short -q
```

### 3.2 Security Controls Explained

1. **Network Denial (`--network none`):**
   - The container has no network interfaces other than a disconnected loopback. Outbound connections, socket creation, DNS requests, and package downloads immediately fail with `OSError: Network is unreachable`.
2. **Resource Throttling (`--memory 512m`, `--cpus 1.0`, `--pids-limit 64`):**
   - Hard memory ceiling of 512MB RAM and 512MB swap. If exceeded, the Linux kernel OOM-killer instantly terminates the container process.
   - CPU quota limited to 1.0 cores, preventing host CPU starvation.
   - Process limit caps simultaneous processes to 64, thwarting fork bombs.
3. **Least Privilege Execution (`--user 10001:10001`, `--cap-drop ALL`, `--read-only`):**
   - Executes as an unprivileged user (`resquser`, UID 10001) rather than root.
   - All Linux kernel capabilities (e.g. `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`, `CAP_DAC_OVERRIDE`) are completely dropped.
   - Root filesystem `/` is mounted read-only. Untrusted code cannot modify `/usr`, `/lib`, or system binaries.
4. **Safe Temporary Directory Mounts:**
   - The runner creates an isolated, unique host directory via Python's `tempfile.TemporaryDirectory()`.
   - Only this directory is mounted to `/workspace:rw`.
   - Host repository roots, parent directories, `.git`, `.venv`, and `.env` are **never** mounted into the container.
5. **Multi-Stage Timeout & Guaranteed Container Cleanup:**
   - **Docker `--stop-timeout 5`:** This flag only governs the grace period between `SIGTERM` and `SIGKILL` *after* a stop command is issued; it is **not** an execution deadline.
   - **Host-Enforced Timeout:** The host runner enforces the true execution deadline via `subprocess.run(..., timeout=timeout_seconds)`.
   - **Guaranteed Cleanup:** If a timeout occurs, a `finally` block on the host executes:
     ```python
     subprocess.run(["docker", "kill", container_name], capture_output=True)
     subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
     ```
     This ensures zero orphaned or lingering containers on Windows/WSL2.

---

## 4. Explicit Limitations of Docker Sandboxing

Containerization is a strong isolation mechanism, but it is **not a formal security guarantee**:

1. **Shared Host Kernel (WSL2):**
   - Docker on Windows relies on the WSL2 lightweight utility VM. The container shares the Linux kernel of that VM.
   - A zero-day Linux kernel privilege escalation exploit could theoretically break out of the container into the WSL2 VM.
2. **Docker Daemon Privileges:**
   - The Docker daemon itself runs with elevated privileges on the host system. Exposing the Docker socket (`/var/run/docker.sock`) inside a container would grant root host access; RESQ Dev strictly forbids mounting the Docker socket.
3. **In-Container Denial of Service:**
   - Malicious code can still crash its own execution or consume its allocated 512MB RAM until terminated by the OOM killer or host timeout.
4. **Safe Demonstration Mode vs. Production Hosting:**
   - **Safe Demonstration Mode:** In the context of a hackathon demo or local developer tool, this Docker configuration provides effective, industry-standard containment for vetted examples and user-submitted code.
   - **Production Arbitrary Code Execution:** Multi-tenant production hosting of untrusted arbitrary code requires hardware-virtualized microVMs (e.g., AWS Firecracker, gVisor, or Modal/E2B sandbox workers), which are out of scope for the local MVP.

---

## 5. Defense Against Prompt Injection & Invariant Corruption

1. **Separation of Test Invariants from Code:**
   - The LLM is requested to modify **only** the target implementation module (`target.py`).
   - The test harness (`test_target.py`) and property invariants are stored in separate files and are **immutable**.
   - The patch applier strictly validates that the candidate patch applies only to `target.py`. Any attempt by the LLM to modify, delete, or rewrite `test_target.py` is rejected.
2. **Deterministic Verification Gate:**
   - Even if an LLM is prompt-injected into generating a no-op or bypass patch, the patch must still pass the original reproducer test that previously failed. If the reproducer fails, the patch is designated `REJECTED_STILL_FAILS`.

---

## 6. Secrets & Dependency Management

1. **No Secrets in Sandbox:**
   - No environment variables containing API keys (e.g., `GEMINI_API_KEY`, `OPENAI_API_KEY`) are passed into the Docker container.
   - The container runs with an empty environment (`env -i`) plus standard Python path variables.
2. **Static Dependency Pinning:**
   - The sandbox container image is pre-built with pinned versions of `pytest` and `hypothesis`.
   - Untrusted code cannot run `pip install` during verification because the container network is disabled (`--network none`).

---

## 7. Human-in-the-Loop Supervision as a Security Boundary

Automated self-healing agents that autonomously rewrite codebases introduce severe security and operational risks: accidental test assertion deletion, unreviewed supply-chain additions, branch corruption, and silent semantic regressions pushed directly to production.

RESQ Dev enforces human supervision as an active security control:
1. **Zero Autonomous Repository Access:** RESQ Dev executes strictly in isolated temporary directories. It contains no Git commit, merge, or push routines, and has no write permissions to the user's working Git repository.
2. **Mandatory Human Approval Gate:** Candidate patches cannot escape the temporary verification sandbox without manual developer action (e.g., copying the patch or downloading the unified diff).
3. **Protection Against Runaway Autonomous Loops:** Repair cycles are strictly bounded (`max_repair_cycles`, default 1, hard cap 2). This prevents recursive token exhaustion, API credit drain, and denial-of-service via continuous container re-runs.
4. **Separation of Verification from Authorization:** RESQ Dev proves empirical satisfaction of tests within a sandbox; the human developer retains sole authority for approving, merging, and deploying changes to the software system.

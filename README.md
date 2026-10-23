# RESQ Dev

**Human-Supervised AI Verification & Repair Assistant for Python**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-isolated_sandbox-2496ED.svg)](https://www.docker.com/)
[![Hypothesis](https://img.shields.io/badge/testing-hypothesis%20%2B%20pytest-brightgreen.svg)](https://hypothesis.readthedocs.io/)
[![Status](https://img.shields.io/badge/status-master_specification_complete-success.svg)]()

---

## What is RESQ Dev?

Standard unit tests only validate anticipated happy paths and obvious boundary conditions. Production failures in Python typically arise from unanticipated edge cases: unexpected empty sequences, surrogate unicode anomalies, floating-point precision accumulation, or state corruption.

**RESQ Dev** is a **human-supervised verification and repair assistant** that pairs **formal hypothesis discovery** (via Hypothesis + pytest) with **LLM-assisted patch synthesis**, bound together by an **independent, deterministic verification gate** running inside an isolated Docker sandbox.

> [!IMPORTANT]
> **Human-in-the-Loop Supervision:** RESQ Dev is **NOT** a self-healing autonomous bot.
> * It executes tests and evaluates patches **strictly** inside isolated temporary Docker workspaces.
> * It **never** mutates your original files or working Git repository.
> * It **never** commits, merges, pushes, or deploys code.
> * It provides reproducible failure evidence and verified diffs for **you (the developer)** to review, approve, and manually adopt.

```
[Target Module + Invariants]
            │
            ▼ (Execute inside Docker)
[Reproducible Failure: Minimized Input + Seed + Traceback]
            │
            ▼ (Synthesize Candidate Patch)
[LLM Gateway: Mock or Real Provider]
            │
            ▼ (Apply to Isolated Temp Copy; Validate AST)
[Deterministic Re-Verification inside Docker]
            │
            ├── Reproducer Passes AND All Regressions Pass ──► VERIFIED
            └── Otherwise ──────────────────────────────────► REJECTED_*
            │
            ▼
[Explicit Human Developer Review & Approval Gate]
            │
            └── Developer reviews evidence, inspects diff, and manually exports/merges
```

*Core Principle:* A patch is **never** declared verified based on LLM claims, conversational confidence, or successful compilation alone. It is marked `VERIFIED` **if and only if** it passes AST syntax checks, resolves the concrete reproducer test (exit code 0), and passes all existing regression tests inside the Docker sandbox with exit code 0.

---

## Master Documentation Suite

All system designs, security guarantees, and implementation plans are formally defined in the master documentation suite:

* **[PROJECT_CONTEXT.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/PROJECT_CONTEXT.md):** Authoritative context, canonical invariants, system boundaries, and verdict taxonomy.
* **[docs/ARCHITECTURE.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/ARCHITECTURE.md):** System block diagram, component contracts, Docker runner specifications, AST patch applier, SQLite schema, and REST API definitions.
* **[docs/IMPLEMENTATION_PLAN.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/IMPLEMENTATION_PLAN.md):** Dependency-ordered delivery roadmap (Milestones 0 to 5) with explicit acceptance criteria, error conditions, and safe rollback rules.
* **[docs/TESTING_STRATEGY.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/TESTING_STRATEGY.md):** Dual-layer testing architecture, Hypothesis shrinking mechanics, source immutability tests, and benchmark evaluation methodology.
* **[docs/SECURITY.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/SECURITY.md):** Threat model for untrusted code, Docker containment flags (`--network none`, `--memory 512m`, non-root), host timeout enforcement, cleanup guarantees, and WSL2 kernel sharing limitations.
* **[docs/AI_AGENT_PROTOCOL.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/AI_AGENT_PROTOCOL.md):** Rules of engagement for AI-assisted development, read-before-write invariants, verification diff report templates, and change-control procedures.

---

## Prerequisites

1. **Operating System:** Windows 10/11 with WSL2 backend.
2. **Python:** Python 3.11 or higher installed.
3. **Docker:** Docker Desktop installed, running, and configured with Linux containers.
4. **Git:** Installed and configured.

---

## Quickstart & Setup

### 1. Environment Preparation
Ensure your Python virtual environment is activated:
```powershell
# In PowerShell (within resq-dev root):
.venv\Scripts\Activate.ps1
```

Copy the environment template and configure settings if using an external LLM:
```powershell
Copy-Item .env.example .env
```

### 2. Build the Docker Execution Sandbox
Before executing any verification tasks, build the local sandbox image:
```powershell
powershell -ExecutionPolicy Bypass -File docker/build_sandbox.ps1
```
Verify that the container image was built successfully:
```powershell
docker run --rm --network none resq-sandbox:latest pytest --version
```

### 3. Run the Milestone 1 Standalone Vertical Slice
The core verification engine is completely independent of web servers or databases:
```powershell
pytest tests/test_pipeline_vertical.py -v
```
This test:
1. Spawns an isolated Docker container with `--network none` and `--memory 512m`.
2. Ingests a known buggy function (`benchmarks/fixtures/01_off_by_one.py`).
3. Executes Hypothesis to capture the edge-case failure and minimized input.
4. Synthesizes a candidate patch using `MockLLMProvider`.
5. Applies the patch to an isolated temporary copy and verifies AST syntax.
6. Re-executes the reproducer and regression tests inside Docker.
7. Asserts the verdict is deterministically `VERIFIED`.

---

## Running the Full Application (Milestones 3 & 4)

### Start the FastAPI Backend
```powershell
uvicorn resq.api.app:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation will be available at: `http://127.0.0.1:8000/docs`

### Start the Streamlit Frontend Dashboard
In a separate terminal:
```powershell
streamlit run src/resq/ui/app.py
```
Open `http://localhost:8501` in your browser.

---

## Running the Benchmark Evaluation Suite (Milestone 5)

To evaluate RESQ Dev's edge-case discovery and verification capabilities against the four curated benchmark fixtures:
```powershell
python benchmarks/run_benchmarks.py
```
This will print an evaluation table reporting discovery latency, minimized input values, and deterministic verification outcomes.

---

## License

This project is developed for hackathon demonstration. All rights reserved.

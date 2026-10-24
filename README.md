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

## Configuration & Local `.env` Setup

RESQ Dev supports project-local configuration via `.env` placed in the project root directory.

### Precedence Policy
1. **Explicit Environment Variables** (set in PowerShell, bash, or container host) take highest precedence and override `.env` values.
2. **Project-local `.env` file** (located in the RESQ Dev project root) is automatically loaded by the settings system regardless of the working directory from which the server or script was launched.
3. **Built-in Defaults** apply when an option is neither in the environment nor in `.env`.

### Supported Configuration Variables and Aliases

| Variable | Aliases | Default | Description |
|---|---|---|---|
| `RESQ_LLM_PROVIDER` | `LLM_PROVIDER` | `mock` | Selects agent decision engine: `"gemini"` or `"mock"`. |
| `GEMINI_API_KEY` | `RESQ_GEMINI_API_KEY`, `GOOGLE_API_KEY` | `""` | Google Gemini API key. Required when provider is `"gemini"`. |
| `RESQ_GEMINI_MODEL` | `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier used for decision cycles. |
| `RESQ_AGENT_MAX_CYCLES` | `AGENT_MAX_CYCLES` | `8` | Maximum observe-reason-act cycles per verification job. |
| `RESQ_AGENT_MAX_TOOL_CALLS`| `AGENT_MAX_TOOL_CALLS` | `12` | Maximum total tool calls per verification job. |
| `DOCKER_IMAGE_NAME` | — | `resq-sandbox:latest` | Tag of the isolated execution sandbox container. |
| `MAX_EXECUTION_TIMEOUT_SECONDS` | — | `10` | Maximum runtime in seconds per sandbox execution. |
| `DATABASE_URL` | — | `sqlite:///./resq.db` | SQLite persistence database connection URI. |

> [!CAUTION]
> **Git Secret Protection:** The `.env` file is ignored by Git (`.gitignore`). Never commit API keys to version control. Use `.env.example` as a template with placeholders only.

---

## Running the Application

### 1. Select LLM Mode in `.env`

**Option A — Deterministic Offline / Mock Mode (Default):**
```dotenv
RESQ_LLM_PROVIDER=mock
```
Uses the built-in evidence-driven mock provider. Ideal for offline development, CI/CD, and deterministic regression testing without network requests or API costs.

**Option B — Live Gemini Agentic Loop:**
```dotenv
RESQ_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_real_gemini_api_key_here
RESQ_GEMINI_MODEL=gemini-2.5-flash
```
Uses Google GenAI SDK to drive genuine model-reasoned decision cycles and structured tool selections.

### 2. Start the FastAPI Backend
```powershell
uvicorn resq.api.app:app --host 127.0.0.1 --port 8000 --reload
```
- API Base: `http://127.0.0.1:8000`
- Interactive OpenAPI Docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/v1/health` (reports `llm_provider` and safe `credential_configured` flag).

### 3. Start the React.js + TypeScript Frontend
In a separate terminal:
```powershell
cd frontend
npm run dev
```
Open `http://localhost:5173` in your browser.

To verify the production bundle:
```powershell
cd frontend
npm run build
```

---

## Submitting a Verification Job

### Example: Reproducible Defect

Submit the following code through the React UI or the REST API:

**Target Source (`add.py`):**
```python
def add(a, b):
    return a - b
```

**Test (`test_add.py`):**
```python
def test_add():
    assert add(2, 3) == 5
```

### Via REST API:
```powershell
curl -X POST http://127.0.0.1:8000/api/v1/jobs `
  -H "Content-Type: application/json" `
  -d '{
    "source_code": "def add(a, b):\n    return a - b\n",
    "test_code": "def test_add():\n    assert add(2, 3) == 5\n",
    "verification_goal": "Fix off-by-subtraction error in add function"
  }'
```

---

## Inspecting Persisted Traces

Every agent decision cycle, tool execution, and truth-gate evaluation is persisted in SQLite (`resq.db`).

1. **In the React UI:** Navigate to the **Agent Decision Trace** tab to view the live timeline of steps, reasoning explanations, tool arguments, and container execution observations.
2. **Via REST API:**
   ```powershell
   curl http://127.0.0.1:8000/api/v1/jobs/<job-id>/trace
   ```
3. **Direct SQLite Query:**
   ```powershell
   python -c "import sqlite3; con=sqlite3.connect('resq.db'); print(con.execute('SELECT step_number, action, observation FROM agent_traces WHERE job_id=\"<job-id>\" ORDER BY step_number').fetchall())"
   ```

---

## Interpreting Truth-Gate Verdicts

The **DeterministicTruthGate** evaluates empirical test outcomes from the Docker container. It never trusts LLM claims of success:

| Verdict | Meaning | Acceptance Conditions |
|---|---|---|
| `VERIFIED` | Repair succeeded and verified | Baseline demonstrated failure, candidate AST valid, reverification tests exit code 0, no regressions. |
| `NO_FAILURE_FOUND` | No defect demonstrated | Baseline tests pass exit code 0 before any repair; nothing to fix. |
| `REJECTED_STILL_FAILS` | Candidate failed verification | Reverification test exit code != 0; defect persists. |
| `REJECTED_SYNTAX_ERROR` | Malformed patch | Candidate patch failed Python AST parsing or compilation. |
| `REJECTED_REGRESSION` | Side effects detected | Existing regression tests broke upon applying the candidate patch. |
| `INSUFFICIENT_EVIDENCE` | Unprovable outcome | Verification tests missing, baseline evidence absent, or ambiguous logs. |
| `TIMEOUT_EXCEEDED` | Execution boundary hit | Sandbox container exceeded maximum allotted time limit. |
| `INFRASTRUCTURE_ERROR` | Docker/Host failure | Docker daemon unreachable, container initialization failure (exit 125). |
| `LLM_ERROR` | Provider failure | Gemini API quota exhausted, network dropped, or malformed provider response. |

---

## Troubleshooting Guide

### 1. Missing Gemini API Key (`HTTP 400 Bad Request`)
- **Symptom:** Submitting a job returns `400 Bad Request: Gemini LLM provider requested (RESQ_LLM_PROVIDER=gemini), but no API key was configured...`.
- **Cause:** `RESQ_LLM_PROVIDER=gemini` is set in `.env` or system environment, but `GEMINI_API_KEY` is empty or missing.
- **Solution:** Add `GEMINI_API_KEY=your_key` to `.env` or switch to offline mode with `RESQ_LLM_PROVIDER=mock`. Silent fallback to mock is strictly prohibited.

### 2. Invalid Gemini API Key or Quota Limit (`LLM_ERROR`)
- **Symptom:** Job status transitions to `FAILED` with verdict `LLM_ERROR`.
- **Cause:** Google GenAI API returned 401 Unauthorized, 403 Forbidden, or 429 Quota Exceeded.
- **Solution:** Check your Google AI Studio quota and verify that the key in `.env` is active.

### 3. Docker Infrastructure Error (`INFRASTRUCTURE_ERROR` / Exit Code 125)
- **Symptom:** Verification fails immediately with `INFRASTRUCTURE_ERROR`.
- **Cause:** Docker Desktop is not running, or the `resq-sandbox:latest` image has not been built.
- **Solution:** Ensure Docker Desktop is active and run:
  ```powershell
  powershell -ExecutionPolicy Bypass -File docker/build_sandbox.ps1
  ```

### 4. Sandbox Timeouts (`TIMEOUT_EXCEEDED`)
- **Symptom:** Job terminates with `TIMEOUT_EXCEEDED`.
- **Cause:** Candidate code entered an infinite loop or test took longer than `MAX_EXECUTION_TIMEOUT_SECONDS` (default: 10s).
- **Solution:** Inspect candidate code in the trace tab or increase `MAX_EXECUTION_TIMEOUT_SECONDS` in `.env` for large test suites.

---

## Test Suites

```powershell
# 1. Non-Docker unit and agent tests (163 tests)
pytest -k "not docker" -v

# 2. Provider policy and configuration tests (7 tests)
pytest tests/test_provider_policy.py -v

# 3. Deterministic truth gate adversarial tests (9 tests)
pytest tests/test_truth_gate_adversarial.py -v

# 4. Docker sandbox hardening tests (16 tests)
pytest tests/test_docker_hardening.py tests/test_docker_runner.py -v

# 5. Full vertical slice pipeline test (Docker + Hypothesis + Pipeline)
pytest tests/test_pipeline_vertical.py -v

# 6. Frontend TypeScript verification and production build
cd frontend
npm run build
```

---

## License

This project is developed for hackathon demonstration. All rights reserved.


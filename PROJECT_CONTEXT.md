# RESQ Dev — Master Project Context & Specification

> **Authoritative Root Document**  
> Version: 1.0.0  
> Status: Active / Canonical Reference  
> Last Updated: 2026-10-23

---

## 1. Executive Summary & Vision

**RESQ Dev** is a **human-supervised AI verification and repair assistant** for Python. It is designed to assist software engineers by discovering subtle edge-case bugs missed by standard tests, capturing reproducible failure artifacts, proposing targeted candidate patches, and independently verifying those patches inside an isolated Docker sandbox.

**Crucial System Boundary:** RESQ Dev is **NOT** a fully autonomous self-healing agent. It operates strictly as an intelligent assistant under human supervision:
* It analyzes code and verifies candidate patches **exclusively** within isolated temporary Docker workspaces.
* It **never** modifies the developer's original source code or the working Git repository.
* It **never** commits, merges, pushes, or deploys changes autonomously.
* A human developer retains sole authority and must explicitly review, approve, and adopt any patch.

```
[Raw Module + Invariants]
         │
         ▼
[Deterministic Test Execution (Docker)]
         │
         ├───► Exit Code == 0 ──────────────► [NO_FAILURE_FOUND]
         ├───► Unparseable Failure ─────────► [INSUFFICIENT_EVIDENCE]
         │
         ▼ (Reproducible Failure Captured: Seed, Minimized Input, Traceback)
[Probabilistic Patch Synthesis (LLM Gateway)]
         │
         ├───► API / Network Error ─────────► [LLM_ERROR]
         │
         ▼ (Candidate Patch Synthesized)
[AST Syntax & Safety Gate]
         │
         ├───► Invalid Python Syntax ───────► [REJECTED_SYNTAX_ERROR]
         │
         ▼ (Patch Applied to Isolated Temporary Copy; Diff Generated)
[Deterministic Re-Verification (Docker)]
         │
         ├───► Reproducer Still Fails ──────► [REJECTED_STILL_FAILS] (Bounded Retry or Halt)
         ├───► Baseline Tests Fail ─────────► [REJECTED_REGRESSION]
         ├───► Container Timeout ───────────► [TIMEOUT_EXCEEDED]
         │
         ▼ (Exit Code 0 on Reproducer AND All Regression Tests)
  [VERIFIED] (Empirical Test Verification in Sandbox Workspace)
         │
         ▼
[Human Review & Explicit Developer Approval Gate]
         │
         └───► Developer inspects evidence, reviews diff, and manually applies/discards
```

---

## 2. Core Architectural Invariants

Every component, contributor, and AI agent working on RESQ Dev must uphold these non-negotiable rules:

1. **Human-Supervised Assistant (No Autonomous Actions):**
   RESQ Dev is an interactive developer tool, not an autonomous self-healing system. It must **never** automatically alter the user's working files, write to the active repository, create Git commits, merge branches, push to remotes, or trigger deployments. Every patch adoption requires explicit human developer review and action.
2. **Bounded, Visible Repair Cycles (No Infinite Loops):**
   Any retry or patch-refinement loop must be strictly bounded (`max_repair_cycles`, default 1, hard maximum 2), completely visible in logs and the user interface, and halt immediately when the budget is exhausted. Hidden, autonomous, or unbounded repair loops are strictly prohibited.
3. **Empirical Verification, Never "Proof":**
   Passing property tests, reproducers, and regressions proves that the code satisfies the tested inputs and invariants. It is rigorous empirical verification; it is **never** described as "formal mathematical proof of correctness" or "guaranteed bug-free code."
4. **Deterministic Truth Gate:**
   An LLM's conversational claims, confidence scores, or self-evaluations are never treated as verification. A patch is designated `VERIFIED` **if and only if** it passes AST syntax validation, resolves the concrete reproducer test (exit code 0), and passes all existing regression tests inside the Docker sandbox with exit code 0.
5. **Mandatory Sandboxing (No Unsandboxed Fallback):**
   Untrusted user code and AI-generated patches execute **strictly** inside a resource-throttled Docker container. If Docker is unavailable or the daemon is down, the system raises `INFRASTRUCTURE_ERROR` and halts. Under no circumstances will RESQ Dev execute untrusted submitted code through an unsandboxed host fallback.
6. **Original Source Immutability:**
   Candidate patches are applied exclusively to an ephemeral, isolated copy of the code in a temporary directory. The user's original source file is read-only during the verification lifecycle. Rejected patches leave zero trace on the original source.
7. **Decoupled Vertical Slice:**
   The core verification engine (Milestone 1) is completely decoupled from web frameworks (FastAPI), persistence (SQLite), UI (Streamlit), and external network LLMs. It operates as a pure Python engine with a deterministic `MockLLMProvider` and containerized execution runner.
8. **Host-Enforced Timeouts:**
   Docker's `--stop-timeout` flag controls only the grace period between `SIGTERM` and `SIGKILL` *after* a stop command is issued. The host runner itself must enforce the hard execution deadline (via Python `subprocess.run(timeout=...)`) and actively terminate and clean up timed-out containers.

---

## 3. Authoritative Status & Verdict Taxonomy

All APIs, database records, engine events, and UI badges must adhere strictly to these mutually exclusive verdicts:

| Verdict | Classification | Precise Operational Condition |
| :--- | :--- | :--- |
| **`VERIFIED`** | **Deterministic Success** | Candidate patch passed AST syntax check, reproducer test exited 0, and all required baseline regression tests exited 0 inside Docker. |
| **`NO_FAILURE_FOUND`** | **Deterministic Completion** | Initial property-based test run ran to completion without discovering any failing case. |
| **`REJECTED_STILL_FAILS`** | **Deterministic Failure** | Candidate patch applied cleanly, but the reproducer test still failed (exit code != 0). |
| **`REJECTED_REGRESSION`** | **Deterministic Failure** | Candidate patch resolved the reproducer, but caused one or more baseline regression tests to fail. |
| **`REJECTED_SYNTAX_ERROR`** | **Static Syntax Failure** | Candidate patch produced invalid Python code or unparseable AST; rejected before execution. |
| **`INSUFFICIENT_EVIDENCE`** | **Engine Limitation** | Property test failed or crashed, but the engine could not parse or extract a reproducible failure artifact or minimized input. |
| **`TIMEOUT_EXCEEDED`** | **Resource Ceiling** | Execution inside Docker exceeded the host-enforced execution deadline; container killed. |
| **`LLM_ERROR`** | **External API Failure** | LLM provider timed out, returned rate-limit errors, authentication failures, or malformed API payloads. |
| **`INFRASTRUCTURE_ERROR`** | **Operational Failure** | Docker daemon unreachable, sandbox image missing, container mount failed, or OS system error. |

---

## 4. System Scope & Boundaries

### 4.1 In Scope (MVP)
* **Single-Module Python Targets:** Ingesting a single Python file (`target.py`) and an optional test/invariant module (`test_target.py`).
* **Hypothesis & Pytest Execution:** Automated execution of property tests to discover edge cases (numerical limits, empty collections, unicode strings, float precision).
* **Failure Artifact Capture:** Capturing full stdout/stderr, tracebacks, seeds, and Hypothesis minimized falsifying examples.
* **Deterministic Mock Provider:** Built-in fixture provider for zero-cost, offline, deterministic testing of the verification pipeline.
* **Replaceable LLM Gateway:** Abstract `LLMProvider` interface allowing interchangeable AI backends.
* **Docker Isolation:** Enforced container execution with `--network none`, `--memory 512m`, `--cpus 1.0`, `--user 10001`, and isolated ephemeral mounts.
* **Interactive UI:** Streamlit dashboard displaying code inputs, execution timeline, failure evidence cards, and unified diffs.
* **Lightweight Persistence:** SQLite database storing jobs, artifacts, patches, and verdicts.

### 4.2 Out of Scope (Explicitly Deferred)
* **Autonomous Self-Healing / Unattended Code Modification:** Automatically overwriting original source files or the team's working repository without developer review.
* **Autonomous Git Operations:** Automatically committing, merging, branching, or pushing to local or remote Git repositories.
* **Autonomous Deployments:** Triggering CI/CD pipelines, staging pushes, or production deployments.
* **Unbounded Repair Loops:** Unlimited retry loops or open-ended autonomous agent iteration.
* Multi-file Python packages, `setup.py`/`pyproject.toml` workspace builds (deferred to post-hackathon).
* Multi-language support (JavaScript, Rust, Go; strictly Python for MVP).
* Complex multi-agent debate protocols or autonomous agent swarms.
* Distributed task queues (Celery, Redis) or container orchestration (Kubernetes).
* Multi-tenant untrusted hosting claims (Docker provides containment for developer tooling, not multi-tenant cloud security).

---

## 5. System Components & Architecture Overview

The system consists of five distinct, loosely coupled layers:

1. **Execution Worker (`src/resq/execution/`):**
   Implements the abstract `ExecutionEnvironment`. The primary implementation is `DockerExecutionRunner`, which wraps `docker run` with strict memory, CPU, process, and network limits, accompanied by rigorous container cleanup.
2. **Verification Engine (`src/resq/engine/`):**
   Pure Python core coordinating failure discovery, failure artifact parsing (`FailureAnalyzer`), AST syntax validation, and temporary-workspace patch application (`PatchApplier`).
3. **LLM Gateway (`src/resq/llm/`):**
   Abstract `LLMProvider` interface. Implements `MockLLMProvider` for deterministic vertical slice tests and a replaceable provider for real AI synthesis in Milestone 2.
4. **Backend API & State Store (`src/resq/api/`, `src/resq/database.py`):**
   FastAPI application managing asynchronous job lifecycles and persisting runs to an embedded SQLite database.
5. **Frontend Dashboard (`src/resq/ui/`):**
   Streamlit interface providing code editors, live progress timelines, minimized input inspection, and verified diff visualization.

---

## 6. Authoritative Repository Layout

```text
resq-dev/
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
├── PROJECT_CONTEXT.md
│
├── docker/
│   ├── Dockerfile.sandbox            # Minimal python:3.11-slim, pytest, hypothesis, user 10001
│   └── build_sandbox.ps1             # Windows PowerShell build script
│
├── docs/
│   ├── ARCHITECTURE.md               # Technical specifications & component designs
│   ├── IMPLEMENTATION_PLAN.md        # Milestone roadmap (M0 to M5) & acceptance criteria
│   ├── TESTING_STRATEGY.md           # Verification methodology & test specifications
│   ├── SECURITY.md                   # Threat model & Docker sandbox boundary
│   └── AI_AGENT_PROTOCOL.md          # Multi-agent collaboration rules
│
├── src/
│   └── resq/
│       ├── __init__.py
│       ├── config.py                 # Pydantic-settings
│       ├── database.py               # SQLite session & engine (Milestone 3)
│       ├── models.py                 # Pure domain models (Job, FailureArtifact, Patch, Verdict)
│       │
│       ├── engine/                   # Verification Core (Decoupled & Independent)
│       │   ├── __init__.py
│       │   ├── pipeline.py           # Core orchestrator: test -> capture -> patch -> verify
│       │   ├── failure_analyzer.py   # Traceback & Hypothesis minimized example extraction
│       │   └── patch_applier.py      # AST validation & isolated temp directory patching
│       │
│       ├── execution/                # Execution Worker
│       │   ├── __init__.py
│       │   ├── base.py               # Abstract ExecutionEnvironment interface
│       │   └── docker_runner.py      # Docker execution with network & resource limits
│       │
│       ├── llm/                      # Replaceable LLM Gateway
│       │   ├── __init__.py
│       │   ├── base.py               # Abstract LLMProvider interface
│       │   ├── prompts.py            # Failure context formatting & structured diff prompts
│       │   └── mock_provider.py      # Deterministic mock provider for vertical slice & tests
│       │                             # (Real provider added in Milestone 2)
│       │
│       ├── api/                      # FastAPI Service (Milestone 3)
│       │   ├── __init__.py
│       │   ├── app.py
│       │   ├── routes.py
│       │   └── schemas.py
│       │
│       └── ui/                       # Streamlit Application (Milestone 4)
│           ├── __init__.py
│           ├── app.py
│           └── components.py
│
├── benchmarks/                       # Deterministic Test Fixtures & Evaluation
│   ├── fixtures/
│   │   ├── 01_off_by_one.py
│   │   ├── 02_empty_collection.py
│   │   ├── 03_unicode_sanitization.py
│   │   └── 04_precision_rounding.py
│   └── run_benchmarks.py
│
└── tests/                            # Internal Test Suite
    ├── conftest.py
    ├── test_docker_runner.py         # Validates container timeout, network drop, cleanup
    ├── test_failure_analyzer.py      # Validates parsing of Hypothesis failures & errors
    ├── test_patch_applier.py         # Validates AST checks, diffs, and ORIGINAL SOURCE IMMUTABILITY
    ├── test_pipeline_vertical.py     # Milestone 1 Standalone Vertical Slice Test
    └── test_api.py                   # FastAPI endpoint lifecycle tests (Milestone 3)
```

---

## 7. Master Documentation Index

All technical inquiries and implementations must align with the specialized master documents:

* System Architecture & Contracts: [docs/ARCHITECTURE.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/ARCHITECTURE.md)
* Implementation Roadmap & Milestones: [docs/IMPLEMENTATION_PLAN.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/IMPLEMENTATION_PLAN.md)
* Testing Strategy & Verification Rules: [docs/TESTING_STRATEGY.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/TESTING_STRATEGY.md)
* Threat Model & Sandbox Boundaries: [docs/SECURITY.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/SECURITY.md)
* AI Agent Rules & Collaboration Protocol: [docs/AI_AGENT_PROTOCOL.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/docs/AI_AGENT_PROTOCOL.md)
* Developer Setup & User Guide: [README.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/README.md)

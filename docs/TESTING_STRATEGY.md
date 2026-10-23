# RESQ Dev — Testing Strategy & Verification Methodology

> **Verification Methodology & Test Specifications**  
> Status: Authoritative Testing Guide  
> Parent Document: [PROJECT_CONTEXT.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/PROJECT_CONTEXT.md)

---

## 1. Dual-Layer Testing Architecture

Testing in RESQ Dev is divided into two fundamentally distinct domains:

```
┌────────────────────────────────────────────────────────────────────────┐
│ DOMAIN 1: Testing RESQ Dev (Meta-Testing)                              │
│ • Validates that RESQ Dev's own internal code operates correctly.      │
│ • Unit tests, API tests, container lifecycle tests, immutability tests. │
│ • Runs via standard pytest on host environment.                        │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ DOMAIN 2: Verification of Target Code (Target Testing)                 │
│ • How RESQ Dev analyzes and verifies untrusted user code & AI patches. │
│ • Executes Hypothesis property tests inside isolated Docker sandbox.   │
│ • Captures minimized falsifying examples, shrinks failures, re-verifies.│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Domain 1: Testing RESQ Dev (Internal Test Suite)

### 2.1 Scope & Test Matrix

| Test Module | Level | Focus & Assertions |
| :--- | :--- | :--- |
| `tests/test_docker_runner.py` | Integration | Confirms container timeout kills runaway processes, verifies `--network none` drops socket connections, ensures zero orphaned containers. |
| `tests/test_failure_analyzer.py` | Unit | Feeds raw pytest outputs into analyzer; asserts correct parsing of `failing_input`, `traceback`, `seed`; validates `NO_FAILURE_FOUND` and `INSUFFICIENT_EVIDENCE`. |
| `tests/test_patch_applier.py` | Unit | Asserts AST syntax error rejection; verifies unified diff generation; **asserts original source code immutability**. |
| `tests/test_pipeline_vertical.py` | End-to-End | Executes the Milestone 1 vertical slice inside Docker using `MockLLMProvider`; asserts final verdict is `VERIFIED`; **verifies bounded repair cycle halts at `max_repair_cycles` without infinite loop**. |
| `tests/test_api.py` | Integration | Uses FastAPI `TestClient` to validate job creation, state polling, and 404/422 error states. |

### 2.2 Mandatory Original Source Immutability Test
To guarantee that candidate patches never corrupt or mutate user source code during evaluation, `tests/test_patch_applier.py` must enforce:

```python
def test_original_source_immutability_on_rejection(tmp_path):
    # Setup original file
    original_code = "def add(a, b): return a - b\n"
    target_file = tmp_path / "target.py"
    target_file.write_text(original_code, encoding="utf-8")
    initial_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()

    # Attempt to apply a broken patch
    broken_patch = "def add(a, b): return a * b\n"
    applier = PatchApplier()
    
    # Apply patch in isolated copy
    patched_dir, diff = applier.prepare_patch_workspace(target_file, broken_patch)
    
    # Assert original file was NEVER modified
    current_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
    assert current_hash == initial_hash, "CRITICAL: Original source file was mutated during patch trial!"
    assert target_file.read_text(encoding="utf-8") == original_code
```

### 2.3 Bounded Repair Cycle Enforcement Test
To guarantee that RESQ Dev never enters an infinite, hidden, or autonomous repair loop, `tests/test_pipeline_vertical.py` must enforce:

```python
def test_pipeline_halts_at_bounded_repair_cycles():
    # Configure pipeline with max_repair_cycles=1
    pipeline = VerificationPipeline(max_repair_cycles=1)
    
    # Run pipeline with a mock provider that intentionally produces failing patches
    result = pipeline.run(buggy_code, invariants, mock_always_failing_provider)
    
    # Assert pipeline executed exactly 1 repair attempt, did not loop, and halted with terminal verdict
    assert result.total_repair_cycles == 1
    assert result.verdict in [Verdict.REJECTED_STILL_FAILS, Verdict.REJECTED_REGRESSION]
```

---

## 3. Domain 2: Verification of Target Code (Hypothesis Engine)

### 3.1 Hypothesis Execution Inside Docker
When RESQ Dev executes property-based tests on submitted code:
1. **Invocation:** Pytest is invoked inside the Docker container pointing to the temporary workspace:
   ```bash
   pytest --tb=short -q --hypothesis-show-statistics
   ```
2. **Deterministic Reproducibility via Seeds:**
   - Hypothesis logs the random seed when a test fails (e.g., `Hypothesis: test_foo failed with seed 123456789`).
   - The engine captures this seed in `FailureArtifact.seed`.
   - When re-verifying a candidate patch, the engine runs the test with `@seed(...)` or `--hypothesis-seed` to ensure the patch is evaluated against the exact failing sequence before running broad new examples.
3. **Shrinking & Minimized Inputs:**
   - Hypothesis automatically shrinks failure payloads to their simplest form (e.g., reducing a 100-character string to `""` or `"\x00"`).
   - The `FailureAnalyzer` parses the `Falsifying example:` block and extracts the minimal argument mapping:
     ```text
     Falsifying example: test_parse_date(date_str='')
     ```
     Extracted artifact: `{"date_str": "''"}`.

### 3.2 Handling Non-Failing and Indeterminate Runs
* **`NO_FAILURE_FOUND`:**
  - If the test suite completes with exit code 0 and all Hypothesis examples pass:
  - The engine marks the run `NO_FAILURE_FOUND` and does not call the LLM.
* **`INSUFFICIENT_EVIDENCE`:**
  - If the test suite fails (exit code != 0), but the failure is unparseable (e.g. fatal segfault, interrupted execution, or unformatted pytest crash without an identifiable traceback):
  - The engine marks the run `INSUFFICIENT_EVIDENCE` rather than feeding corrupted context to the LLM.

---

## 4. Deterministic Verification Gate Rules

To eliminate false positives, a candidate patch must satisfy three consecutive gates:

```
[Candidate Patch]
       │
       ▼ Gate 1: Static AST Validation
[Does it parse as valid Python AST without syntax errors?]
       ├── NO ──► REJECTED_SYNTAX_ERROR
       └── YES
            │
            ▼ Gate 2: Concrete Reproducer Verification
       [Does the specific reproducer test that previously failed now pass (Exit Code 0)?]
            ├── NO ──► REJECTED_STILL_FAILS
            └── YES
                 │
                 ▼ Gate 3: Baseline Regression Verification
            [Do all pre-existing baseline unit tests still pass (Exit Code 0)?]
                 ├── NO ──► REJECTED_REGRESSION
                 └── YES
                      │
                      ▼
                 [VERIFIED]
```

*Under no circumstances may a patch skip Gate 2 or Gate 3.*

### 4.1 Truthful Verification Reporting Boundary
Verification results must report strictly what was actually tested:
* The specific reproducer test and minimized input that passed.
* The pre-existing baseline unit tests that passed without regression.
* The random seed used for deterministic reproduction.

**Explicit Non-Claims:**
* RESQ Dev does **not** claim formal mathematical proof of correctness.
* RESQ Dev does **not** claim guaranteed bug-free software.
* Verification demonstrates that the candidate patch empirically satisfies the specified property tests within the tested input domain. Human developer review is mandatory prior to merging or deploying.

---

## 5. Benchmark Evaluation Methodology

The benchmark evaluation harness (`benchmarks/run_benchmarks.py`) executes a reproducible performance and correctness audit across 4 curated fixtures:

1. **`01_off_by_one.py`:** Boundary index in binary search or sliding window.
2. **`02_empty_collection.py`:** Unchecked empty list or `None` return value.
3. **`03_unicode_sanitization.py`:** String sanitization failing on null-bytes (`\x00`) or surrogate characters.
4. **`04_precision_rounding.py`:** Floating-point comparison failing on precision accumulation.

### Evaluation Metrics Collected
* **Discovery Latency ($T_{reproduce}$):** Time in seconds for Hypothesis inside Docker to discover and shrink the failure.
* **Failing Input Captured:** Value and type of minimized input.
* **Synthesis Latency ($T_{synthesis}$):** Time in seconds for the LLM Gateway to return a candidate patch.
* **Verification Latency ($T_{verify}$):** Time in seconds for Docker re-verification.
* **Verdict:** Final classification (`VERIFIED`, `REJECTED_*`).

No claims of "under 15-second resolution" are made; actual measured latencies are reported transparently in the evaluation table.

# RESQ Dev — AI-Agent Collaboration & Review Protocol

> **Operating Rules & Change-Control Protocol for AI Agents**  
> Status: Authoritative Collaboration Guide  
> Parent Document: [PROJECT_CONTEXT.md](file:///c:/Users/akshitha/Desktop/RESQ_Dev/PROJECT_CONTEXT.md)

---

## 1. Multi-Agent Roles & Responsibilities

Development and review of RESQ Dev follow an explicit tripartite collaboration model:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        HUMAN TECHNICAL LEAD                            │
│                 (Sole Authority & Final Decision Maker)                 │
└───────────────────▲────────────────────────────────▲───────────────────┘
                    │                                │
                    ▼                                ▼
┌────────────────────────────────────────┐ ┌─────────────────────────────┐
│ ANTIGRAVITY (Lead Implementer)         │ │ CHATGPT (Planning & Review) │
│ • Primary coding and execution agent   │ │ • Design reviewer & auditor │
│ • Inspects workspace before edits      │ │ • Challenges assumptions    │
│ • Runs tests inside Docker sandbox     │ │ • Validates documentation   │
│ • Generates minimal, surgical diffs    │ │ • Reviews implementation    │
└───────────────────┬────────────────────┘ └──────────────┬──────────────┘
                    │                                     │
                    └──────────────────┬──────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│ MODEL B / ADVERSARIAL AGENT (Edge-Case & Invariant Reviewer)          │
│ • Inspects proposed patches for subtle regressions                     │
│ • Formulates hostile inputs to test boundary conditions                │
│ • Verifies that empirical testing is not claimed as formal proof       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Mandatory Rules of Engagement for AI Agents

Every agent interacting with the RESQ Dev codebase must unconditionally adhere to these rules:

### Rule 1: Read-Before-Write
Before proposing code modifications or editing files, the agent **must** read:
1. `PROJECT_CONTEXT.md` to confirm system invariants and canonical vocabulary.
2. The relevant specialized document (`docs/ARCHITECTURE.md`, `docs/SECURITY.md`, etc.).
3. The specific existing file(s) targeted for modification.

### Rule 2: Inspect Before Edit
Agents must never assume file content or rely on stale cached state. Always invoke `view_file` or check Git status to inspect current lines and structure before generating edits.

### Rule 3: Small, Reviewable Increments
Work must be partitioned into small, reviewable commits aligned with the milestone sequence defined in `docs/IMPLEMENTATION_PLAN.md`. Large monolithic rewrites that modify multiple unrelated subsystems simultaneously are strictly forbidden.

### Rule 4: No Unnecessary Dependencies or Refactoring
Agents must not introduce new libraries, frameworks, or utility wrappers unless explicitly specified in `docs/IMPLEMENTATION_PLAN.md`. Unrelated style refactoring, renaming, or cosmetic rewrites of working code are prohibited.

### Rule 5: Non-Destructive Operations & Explicit Approvals
* Agents must **never** delete, overwrite, or replace existing files without explicit user instruction.
* Destructive terminal commands (such as `git clean -fd`, `rm -rf`, or resetting branches) are strictly prohibited.
* Agents must **never** automatically commit, merge, or push changes to Git repositories or trigger automated deployments.
* Architectural changes, database schema alterations, or security boundary adjustments require explicit user confirmation.

### Rule 6: Truthful Verification Reporting
Agents must report actual, unembellished execution outputs:
* Never claim a test passed unless the test was run and returned exit code 0.
* Never describe empirical testing as "formal mathematical proof of correctness" or "guaranteed bug-free code."
* Report exact files changed, terminal commands executed, test results, known limitations, and unresolved risks.

### Rule 7: Documentation Synchrony
When an architectural decision, security assumption, or API contract is modified with user approval, the agent must update the corresponding master documentation files (`PROJECT_CONTEXT.md` and `docs/*.md`) before concluding the task.

### Rule 8: Human-Supervised Assistant Constraints
* RESQ Dev is designed as a human-supervised repair assistant, not an autonomous self-healing system.
* Any repair or retry cycle implemented by an agent must be strictly bounded (`max_repair_cycles <= 2`), transparently logged, and never allowed to loop indefinitely.
* Human developers retain sole authority for reviewing, approving, and applying candidate patches outside the temporary sandbox.

---

## 3. Standardized Verification & Diff Report Template

At the conclusion of every implementation or review turn, the acting agent must submit a report adhering to this markdown structure:

```markdown
### Summary of Work Completed
* Clear, concise description of changes made in this turn.

### Files Modified & Created
* `[path/to/file.py](file:///path/to/file.py)`: Description of changes.

### Terminal Commands Executed & Output
* Command: `docker run ...` / `pytest tests/...`
* Result: `X passed, 0 failed in Y.YYs (Exit Code: 0)`

### Verification Gate Status
* Status: `[VERIFIED | REJECTED_* | TIMEOUT_EXCEEDED | ...]`
* Original Source Immutability Checked: `[YES - Hash Identical | N/A]`

### Known Limitations & Open Risks
* Any boundary condition, performance limitation, or assumption not yet addressed.

### Next Action / Awaiting User Approval
* Specific next step according to `docs/IMPLEMENTATION_PLAN.md`.
```

---

## 4. Conflict Resolution & Precedence Hierarchy

If a conflict or ambiguity arises between models, prompts, or agents, the following hierarchy of authority governs:

1. **Human Technical Lead's explicit instructions.**
2. **`PROJECT_CONTEXT.md` (Authoritative Root Document).**
3. **`docs/SECURITY.md` (Non-negotiable security boundaries).**
4. **`docs/ARCHITECTURE.md` (System interfaces and contracts).**
5. **`docs/IMPLEMENTATION_PLAN.md` (Delivery sequence).**
6. **AI Agent suggestions or planning notes.**

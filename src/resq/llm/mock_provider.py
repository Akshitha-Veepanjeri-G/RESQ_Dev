"""Deterministic mock LLM provider for zero-cost offline testing of the verification loop."""

from typing import Any, Optional
from resq.llm.base import LLMProvider

from resq.models import CandidatePatch, FailureArtifact

# Verified patch for benchmark 01 (binary search off-by-one fix)
VALID_BINARY_SEARCH_PATCH = '''"""Benchmark 01: Off-by-one boundary bug in binary search (FIXED)."""


def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found.

    FIXED: Loop now correctly uses `low <= high` to include boundary elements.
    """
    if not arr:
        return -1

    low = 0
    high = len(arr) - 1

    while low <= high:  # Corrected boundary condition
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1

    return -1
'''

# Patch that still fails the edge case
STILL_FAILING_PATCH = '''def binary_search(arr: list[int], target: int) -> int:
    # Still broken: unchanged loop condition
    if not arr:
        return -1
    low = 0
    high = len(arr) - 1
    while low < high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
'''

# Patch that introduces a regression (e.g. breaks empty array baseline test)
REGRESSION_PATCH = '''def binary_search(arr: list[int], target: int) -> int:
    # Regression: crashes on empty array with IndexError
    low = 0
    high = len(arr) - 1
    if arr[0] == target:  # Crashes on empty array!
        return 0
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
'''

# Malformed patch that fails AST parsing
SYNTAX_ERROR_PATCH = '''def binary_search(arr: list[int], target: int) -> int:
    while low <= high  # Missing colon! SyntaxError
        return mid
'''


class MockLLMProvider(LLMProvider):
    """Deterministic mock provider returning pre-computed candidate patches."""

    provider_name: str = "mock"

    def __init__(
        self,
        mode: str = "valid",
        custom_patch: Optional[str] = None,
        custom_explanation: str = "Mock patch generated for testing.",
        fixture_id: Optional[str] = None,
        patch_map: Optional[dict[str, str]] = None,
        decision_sequence: Optional[list[Any]] = None,
    ):
        """Initializes MockLLMProvider.

        Args:
            mode: One of 'valid', 'still_fails', 'regression', 'syntax_error', or 'custom'.
            custom_patch: Optional explicit patch string to return.
            custom_explanation: Explanatory text for the patch.
            fixture_id: Optional benchmark fixture ID (e.g. 'BM-01', 'BM-02') to auto-select its patch.
            patch_map: Optional dictionary mapping fixture IDs to custom patches.
            decision_sequence: Optional pre-determined list of AgentDecision objects to return in order.
        """
        self.mode = mode
        self.custom_patch = custom_patch
        self.custom_explanation = custom_explanation
        self.fixture_id = fixture_id
        self.patch_map = patch_map or {}
        self.decision_sequence = list(decision_sequence) if decision_sequence else None
        self.decision_index = 0
        self.call_count = 0


    def generate_patch(self, source_code: str, failure: FailureArtifact) -> CandidatePatch:
        """Returns deterministic candidate patch based on configured mode or fixture ID."""
        self.call_count += 1

        # 1. Custom patch takes highest precedence
        if self.custom_patch is not None:
            return CandidatePatch(
                patch_code=self.custom_patch,
                explanation=self.custom_explanation,
                raw_model_response=self.custom_patch,
                provider_name="mock",
            )

        # 2. Patch map lookup for specified fixture_id
        if self.fixture_id and self.fixture_id in self.patch_map:
            patch_code = self.patch_map[self.fixture_id]
            return CandidatePatch(
                patch_code=patch_code,
                explanation=f"Deterministic mock patch mapped for {self.fixture_id}.",
                raw_model_response=patch_code,
                provider_name="mock",
            )

        # 3. Dynamic lookup from benchmark fixture dataset if fixture_id is provided
        if self.fixture_id:
            try:
                from benchmarks.loader import get_fixture_by_id
                fixture = get_fixture_by_id(self.fixture_id)
                if fixture and fixture.candidate_patch:
                    return CandidatePatch(
                        patch_code=fixture.candidate_patch,
                        explanation=f"Deterministic mock patch for {self.fixture_id}.",
                        raw_model_response=fixture.candidate_patch,
                        provider_name="mock",
                    )
            except Exception:
                pass

        # 4. Standard predefined modes
        if self.mode == "valid":
            patch_code = VALID_BINARY_SEARCH_PATCH
            explanation = "Replaced `low < high` with `low <= high` to resolve boundary element search."
        elif self.mode == "still_fails":
            patch_code = STILL_FAILING_PATCH
            explanation = "Attempted patch that leaves off-by-one condition unresolved."
        elif self.mode == "regression":
            patch_code = REGRESSION_PATCH
            explanation = "Attempted patch that resolves property test but breaks empty list baseline test."
        elif self.mode == "syntax_error":
            patch_code = SYNTAX_ERROR_PATCH
            explanation = "Malformed Python patch that triggers SyntaxError."
        elif self.mode == "custom":
            raise ValueError("custom_patch must be provided when mode is 'custom'")
        else:
            raise ValueError(f"Unknown mock provider mode: {self.mode}")

        return CandidatePatch(
            patch_code=patch_code,
            explanation=explanation,
            raw_model_response=patch_code,
            provider_name="mock",
        )

    def decide_action(self, state: Any) -> Any:
        """Determines the next agent verification action based on accumulated state."""
        from resq.agent.models import AgentActionName, AgentCompletionStatus, AgentDecision

        # 1. Custom decision sequence takes precedence (for testing edge cases)
        if self.decision_sequence is not None:
            if self.decision_index < len(self.decision_sequence):
                decision = self.decision_sequence[self.decision_index]
                self.decision_index += 1
                return decision
            return AgentDecision(
                action=AgentActionName.STOP.value,
                reason="Pre-configured test decision sequence exhausted.",
                expected_observation="Halt agent verification.",
                completion_status=AgentCompletionStatus.COMPLETED,
            )

        # 2. Evidence-driven policy based on state observations
        actions_taken = [step.decision.action for step in state.recent_steps]

        # Step A: Run baseline tests if not yet executed
        if not state.has_baseline_run:
            if AgentActionName.INSPECT_SOURCE.value not in actions_taken:
                return AgentDecision(
                    action=AgentActionName.INSPECT_SOURCE.value,
                    arguments={"start_line": 1},
                    reason="Inspect initial source structure and symbols before running tests.",
                    expected_observation="Source code lines and identified symbols.",
                    completion_status=AgentCompletionStatus.CONTINUE,
                )
            return AgentDecision(
                action=AgentActionName.RUN_BASELINE_TESTS.value,
                arguments={},
                reason="Execute baseline pytest suite inside isolated Docker sandbox to detect defects.",
                expected_observation="Pass/fail test status and captured stack traces.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )

        # Step B: Baseline passed completely without any failure
        if state.baseline_passed:
            return AgentDecision(
                action=AgentActionName.STOP.value,
                arguments={},
                reason="Baseline tests ran to completion without discovering any failure.",
                expected_observation="Conclude verification with NO_FAILURE_FOUND.",
                completion_status=AgentCompletionStatus.COMPLETED,
            )

        # Step C: Baseline failed -> Analyze failure evidence
        if not state.current_failure:
            return AgentDecision(
                action=AgentActionName.ANALYZE_FAILURE.value,
                arguments={},
                reason="Extract structured failure artifact (exception, traceback, minimized input, seed).",
                expected_observation="Structured FailureArtifact.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )

        # Step D: If failure is not reproducible
        if state.current_failure and not state.current_failure.is_reproducible:
            if AgentActionName.SUMMARIZE_EVIDENCE.value not in actions_taken:
                return AgentDecision(
                    action=AgentActionName.SUMMARIZE_EVIDENCE.value,
                    arguments={"assessment": "Failure is non-reproducible; insufficient evidence."},
                    reason="Engine cannot reproduce failure deterministically.",
                    expected_observation="Inconclusive evidence report.",
                    completion_status=AgentCompletionStatus.INCONCLUSIVE,
                )
            return AgentDecision(
                action=AgentActionName.STOP.value,
                reason="Halting due to inconclusive failure evidence.",
                expected_observation="Conclude with INSUFFICIENT_EVIDENCE.",
                completion_status=AgentCompletionStatus.INCONCLUSIVE,
            )

        # Step E: Synthesize candidate patch if not yet generated
        if not state.current_patch:
            if AgentActionName.INSPECT_AST.value not in actions_taken:
                return AgentDecision(
                    action=AgentActionName.INSPECT_AST.value,
                    arguments={"target": "source"},
                    reason="Inspect target AST structure before synthesizing candidate patch.",
                    expected_observation="Syntax tree functions and classes.",
                    completion_status=AgentCompletionStatus.CONTINUE,
                )
            return AgentDecision(
                action=AgentActionName.GENERATE_CANDIDATE_PATCH.value,
                arguments={},
                reason="Request candidate patch based on reproducible failure evidence.",
                expected_observation="Candidate patch code and explanation.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )

        # Step F: Validate candidate patch syntax
        if state.patch_syntax_valid is None:
            return AgentDecision(
                action=AgentActionName.VALIDATE_CANDIDATE_PATCH.value,
                arguments={},
                reason="Perform static AST validation on candidate patch before execution.",
                expected_observation="AST syntax check and unified diff.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )

        # Step G: Patch syntax invalid
        if state.patch_syntax_valid is False:
            return AgentDecision(
                action=AgentActionName.STOP.value,
                reason="Candidate patch has invalid Python syntax; rejected by static gate.",
                expected_observation="Conclude with REJECTED_SYNTAX_ERROR.",
                completion_status=AgentCompletionStatus.COMPLETED,
            )

        # Step H: Re-verify patch in sandbox
        if state.reverification_passed is None:
            return AgentDecision(
                action=AgentActionName.RUN_VERIFICATION_TESTS.value,
                arguments={},
                reason="Execute tests against candidate patch in isolated temporary workspace.",
                expected_observation="Pass/fail result of candidate patch.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )

        # Step I: Summarize evidence and stop
        if AgentActionName.SUMMARIZE_EVIDENCE.value not in actions_taken:
            return AgentDecision(
                action=AgentActionName.SUMMARIZE_EVIDENCE.value,
                arguments={"assessment": "Completed empirical re-verification cycle."},
                reason="Assemble collected verification evidence for final report.",
                expected_observation="Summary of all verification checks.",
                completion_status=AgentCompletionStatus.CONTINUE,
            )

        return AgentDecision(
            action=AgentActionName.STOP.value,
            reason="Verification checks completed.",
            expected_observation="Final verification outcome.",
            completion_status=AgentCompletionStatus.COMPLETED,
        )


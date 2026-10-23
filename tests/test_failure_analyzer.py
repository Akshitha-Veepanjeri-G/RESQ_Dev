"""Unit tests for FailureAnalyzer output parsing and evidence extraction."""

from resq.engine.failure_analyzer import FailureAnalyzer
from resq.models import ExecutionResult


class TestFailureAnalyzer:
    """Validates extraction of failure evidence from pytest/Hypothesis outputs."""

    def test_clean_execution_result_analysis(self):
        result = ExecutionResult(
            exit_code=0,
            stdout="3 passed in 0.12s\n",
            stderr="",
        )
        analyzer = FailureAnalyzer()
        artifact = analyzer.analyze(result)
        assert artifact.is_reproducible is False
        assert artifact.failing_input is None
        assert artifact.exception_type is None

    def test_timeout_execution_result_analysis(self):
        result = ExecutionResult(
            exit_code=124,
            stdout="",
            stderr="TIMEOUT_EXCEEDED: Container exceeded hard timeout.\n",
            timed_out=True,
        )
        analyzer = FailureAnalyzer()
        artifact = analyzer.analyze(result)
        assert artifact.is_reproducible is False
        assert "timed out" in artifact.assertion_message.lower()

    def test_hypothesis_failure_extraction(self):
        sample_output = """
============================= test session starts =============================
rootdir: /workspace
collected 4 items

test_target.py ...F                                                      [100%]

================================== FAILURES ===================================
_________________ test_property_finds_all_existing_elements __________________

    @settings(max_examples=50, deadline=None)
    @given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
>   def test_property_finds_all_existing_elements(arr: list[int]):

test_target.py:38: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

    for val in arr:
        idx = binary_search(arr, val)
>       assert idx != -1, f"Failed to find {val} in {arr}"
E       AssertionError: Failed to find 0 in [0]
E       assert -1 != -1

test_target.py:42: AssertionError
---------------------------------- Hypothesis ----------------------------------
Falsifying example: test_property_finds_all_existing_elements(
    arr=[0],
)
You can add @seed(348123984) to this test to reproduce this failure.
=========================== short test summary info ===========================
FAILED test_target.py::test_property_finds_all_existing_elements - AssertionError: Failed to find 0 in [0]
========================= 1 failed, 3 passed in 0.28s =========================
"""
        result = ExecutionResult(
            exit_code=1,
            stdout=sample_output,
            stderr="",
        )
        analyzer = FailureAnalyzer()
        artifact = analyzer.analyze(result)

        assert artifact.is_reproducible is True
        assert artifact.exception_type == "AssertionError"
        assert "Failed to find 0 in [0]" in artifact.assertion_message
        assert artifact.seed == 348123984
        assert artifact.failing_input is not None
        assert "arr=[0]" in artifact.failing_input

    def test_unparseable_corrupt_output(self):
        result = ExecutionResult(
            exit_code=139,
            stdout="Fatal error occurred.\nSegmentation fault (core dumped)\n",
            stderr="",
        )
        analyzer = FailureAnalyzer()
        artifact = analyzer.analyze(result)
        # Cannot extract concrete reproducible input or Python traceback
        assert artifact.is_reproducible is False
        assert artifact.failing_input is None

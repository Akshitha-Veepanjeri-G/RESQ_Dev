import type { BenchmarkPreset } from '../types/api';

export const BENCHMARK_PRESETS: BenchmarkPreset[] = [
  {
    id: 'bm-01',
    title: '01: Off-by-one Binary Search',
    category: 'Loop Boundary Defect',
    defectSummary: 'Loop uses low < high instead of low <= high, missing edge targets.',
    expectedVerdict: 'VERIFIED',
    targetFilename: 'target.py',
    testFilename: 'test_target.py',
    sourceCode: `def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found.

    BUG: Loop uses \`low < high\` instead of \`low <= high\`, which misses the target
    whenever low == high (e.g. single-element arrays or targets at the end).
    """
    if not arr:
        return -1

    low = 0
    high = len(arr) - 1

    while low < high:  # BUG: should be low <= high
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1

    return -1
`,
    invariantsCode: `from hypothesis import given, settings, strategies as st
from target import binary_search

def test_baseline_empty():
    assert binary_search([], 10) == -1

def test_baseline_finds_middle():
    assert binary_search([1, 3, 5], 3) == 1

def test_baseline_not_found():
    assert binary_search([2, 4, 6], 5) == -1

@settings(max_examples=50, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
def test_property_finds_all_existing_elements(arr: list[int]):
    """Invariant: every element physically present in the sorted array must be found."""
    for val in arr:
        idx = binary_search(arr, val)
        assert idx != -1, f"Failed to find {val} in {arr}"
        assert arr[idx] == val
`,
  },
  {
    id: 'bm-02',
    title: '02: Empty & Singleton Collections',
    category: 'Collection Boundary Defect',
    defectSummary: 'Unconditionally accesses [1] on sorted unique set without checking collection length.',
    expectedVerdict: 'VERIFIED',
    targetFilename: 'target.py',
    testFilename: 'test_target.py',
    sourceCode: `"""Target implementation: Finding second smallest unique element."""

from typing import Optional


def find_second_smallest(values: list[int]) -> Optional[int]:
    """Returns the second smallest unique value from a list of integers,
    or None if the collection contains fewer than two unique values.

    BUG: Unconditionally accesses index [1] of the sorted unique elements
    without verifying collection length, causing IndexError on empty or singleton collections.
    """
    sorted_unique = sorted(set(values))
    return sorted_unique[1]  # BUG: IndexError when len(sorted_unique) < 2
`,
    invariantsCode: `from typing import Optional
from hypothesis import given, settings, strategies as st
from target import find_second_smallest


def test_baseline_three_elements():
    assert find_second_smallest([10, 20, 30]) == 20


def test_baseline_unsorted_duplicates():
    assert find_second_smallest([5, 1, 5, 3]) == 3


def test_baseline_two_elements():
    assert find_second_smallest([7, 2]) == 7


def test_property_explicit_empty_collection():
    """Explicit edge case: empty collection must return None."""
    assert find_second_smallest([]) is None


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=-1000, max_value=1000))
def test_property_explicit_singleton_collection(val: int):
    """Explicit edge case: singleton collection must return None."""
    assert find_second_smallest([val]) is None


@settings(max_examples=35, deadline=None)
@given(st.lists(st.integers(min_value=-500, max_value=500), max_size=25))
def test_property_second_smallest_invariants(values: list[int]):
    """Invariant: Returns second smallest unique integer, or None if unique elements < 2."""
    unique = sorted(set(values))
    result = find_second_smallest(values)
    if len(unique) < 2:
        assert result is None, f"Expected None for {values}, got {result}"
    else:
        assert result == unique[1]
`,
  },
  {
    id: 'bm-03',
    title: '03: Duplicate Elements Handling',
    category: 'Sequence Dedup Defect',
    defectSummary: 'Only filters adjacent duplicates, failing on recurring non-consecutive duplicates.',
    expectedVerdict: 'VERIFIED',
    targetFilename: 'target.py',
    testFilename: 'test_target.py',
    sourceCode: `"""Target implementation: Deduplicating list while preserving first-seen order."""


def deduplicate_preserve_order(items: list[int]) -> list[int]:
    """Removes duplicate integers while preserving their first-seen order.

    BUG: Only filters consecutive adjacent duplicates (similar to unix uniq),
    failing when identical elements recur at non-adjacent positions (e.g. [1, 2, 1]).
    """
    if not items:
        return []
    result = [items[0]]
    for x in items[1:]:
        if x != result[-1]:  # BUG: only checks immediate predecessor
            result.append(x)
    return result
`,
    invariantsCode: `from hypothesis import given, settings, strategies as st
from target import deduplicate_preserve_order


def test_baseline_empty():
    assert deduplicate_preserve_order([]) == []


def test_baseline_no_duplicates():
    assert deduplicate_preserve_order([1, 2, 3]) == [1, 2, 3]


def test_baseline_adjacent_duplicates():
    assert deduplicate_preserve_order([1, 1, 2, 2, 3]) == [1, 2, 3]


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(min_value=-50, max_value=50), max_size=30))
def test_property_no_duplicates_in_result(items: list[int]):
    """Invariant 1: The returned sequence must contain no duplicate values."""
    res = deduplicate_preserve_order(items)
    assert len(res) == len(set(res))


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(min_value=-50, max_value=50), max_size=30))
def test_property_contains_all_unique_elements(items: list[int]):
    """Invariant 2: The returned sequence must contain exactly the set of unique values."""
    res = deduplicate_preserve_order(items)
    assert set(res) == set(items)
`,
  },
  {
    id: 'bm-04',
    title: '04: Invalid Inputs & Domain Validation',
    category: 'Input Validation Defect',
    defectSummary: 'ZeroDivisionError on total == 0 and unvalidated bounds on percentage input.',
    expectedVerdict: 'VERIFIED',
    targetFilename: 'target.py',
    testFilename: 'test_target.py',
    sourceCode: `"""Target implementation: Percentage calculation with unvalidated domain boundaries."""


def calculate_percentage(part: float, total: float) -> float:
    """Calculates percentage: (part / total) * 100.

    Contract:
    - total must be strictly positive (> 0); raises ValueError otherwise.
    - part must satisfy 0.0 <= part <= total; raises ValueError otherwise.
    - Returns rounded percentage as float in [0.0, 100.0].

    BUG: Does not validate domain boundaries. Crashes with ZeroDivisionError when total == 0,
    and returns negative or >100% values for out-of-domain inputs without raising ValueError.
    """
    return round((part / total) * 100.0, 2)
`,
    invariantsCode: `import pytest
from hypothesis import given, settings, strategies as st
from target import calculate_percentage


def test_baseline_standard_percentage():
    assert calculate_percentage(25.0, 100.0) == 25.0


def test_baseline_zero_part():
    assert calculate_percentage(0.0, 50.0) == 0.0


def test_baseline_full_percentage():
    assert calculate_percentage(50.0, 50.0) == 100.0


def test_property_zero_total_raises_value_error():
    with pytest.raises(ValueError, match="total must be strictly positive"):
        calculate_percentage(10.0, 0.0)


def test_property_negative_total_raises_value_error():
    with pytest.raises(ValueError, match="total must be strictly positive"):
        calculate_percentage(10.0, -5.0)


def test_property_negative_part_raises_value_error():
    with pytest.raises(ValueError, match="part must be within"):
        calculate_percentage(-1.0, 10.0)


def test_property_part_exceeding_total_raises_value_error():
    with pytest.raises(ValueError, match="part must be within"):
        calculate_percentage(15.0, 10.0)
`,
  },
  {
    id: 'bm-05',
    title: '05: Clean Implementation (No Defect)',
    category: 'Clean Baseline',
    defectSummary: 'Intentionally correct implementation with no defects. All tests pass.',
    expectedVerdict: 'NO_FAILURE_FOUND',
    targetFilename: 'target.py',
    testFilename: 'test_target.py',
    sourceCode: `"""Target implementation: Intentionally correct integer clamp function."""


def clamp(val: int, min_val: int, max_val: int) -> int:
    """Clamps an integer value within the inclusive range [min_val, max_val].

    Contract:
    - min_val must not exceed max_val; raises ValueError otherwise.
    - Returns min_val if val < min_val, max_val if val > max_val, else val.
    """
    if min_val > max_val:
        raise ValueError("min_val must not exceed max_val")
    return max(min_val, min(val, max_val))
`,
    invariantsCode: `import pytest
from hypothesis import given, settings, strategies as st
from target import clamp


def test_baseline_within_range():
    assert clamp(5, 0, 10) == 5


def test_baseline_below_min():
    assert clamp(-5, 0, 10) == 0


def test_baseline_above_max():
    assert clamp(15, 0, 10) == 10


def test_baseline_invalid_range():
    with pytest.raises(ValueError, match="min_val must not exceed max_val"):
        clamp(5, 10, 0)


@settings(max_examples=50, deadline=None)
@given(
    val=st.integers(min_value=-5000, max_value=5000),
    a=st.integers(min_value=-5000, max_value=5000),
    b=st.integers(min_value=-5000, max_value=5000),
)
def test_property_clamped_result_in_range(val: int, a: int, b: int):
    low = min(a, b)
    high = max(a, b)
    result = clamp(val, low, high)
    assert low <= result <= high
`,
  },
];

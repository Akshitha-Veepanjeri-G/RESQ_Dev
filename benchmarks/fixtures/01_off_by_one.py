"""Benchmark 01: Off-by-one boundary bug in binary search.

Contains a subtle off-by-one condition that passes simple middle-element
lookups but fails when the target is at boundary positions or in single-element arrays.
"""

from hypothesis import given, settings, strategies as st


def binary_search(arr: list[int], target: int) -> int:
    """Finds target in sorted array arr using binary search. Returns index or -1 if not found.

    BUG: Loop uses `low < high` instead of `low <= high`, which misses the target
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


# Baseline unit tests (these pass even on the buggy implementation)
def test_baseline_empty():
    assert binary_search([], 10) == -1


def test_baseline_finds_middle():
    assert binary_search([1, 3, 5], 3) == 1


def test_baseline_not_found():
    assert binary_search([2, 4, 6], 5) == -1


# Property-based edge-case test: Fails on buggy implementation, shrinks to arr=[0], target=0
@settings(max_examples=50, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=20).map(sorted))
def test_property_finds_all_existing_elements(arr: list[int]):
    """Invariant: every element physically present in the sorted array must be found."""
    for val in arr:
        idx = binary_search(arr, val)
        assert idx != -1, f"Failed to find {val} in {arr}"
        assert arr[idx] == val

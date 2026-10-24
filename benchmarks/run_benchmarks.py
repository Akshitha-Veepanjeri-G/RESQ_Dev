"""Executable CLI entrypoint for running RESQ Dev verification benchmarks.

Usage:
    python benchmarks/run_benchmarks.py                   # Run all 10 benchmarks
    python benchmarks/run_benchmarks.py --id BM-01        # Run single benchmark
    python benchmarks/run_benchmarks.py --subset BM-01,BM-02
    python benchmarks/run_benchmarks.py --json            # Output deterministic JSON
"""

import argparse
from pathlib import Path
import sys

# Ensure repository root and src are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
src_path = REPO_ROOT / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from benchmarks.runner import BenchmarkRunner


def main():
    parser = argparse.ArgumentParser(
        description="RESQ Dev -- Benchmark Evaluation Suite Runner",
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="Run a single benchmark by ID (e.g. BM-01).",
    )
    parser.add_argument(
        "--subset",
        type=str,
        default=None,
        help="Comma-separated list of benchmark IDs to run (e.g. BM-01,BM-02).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of summary table.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Default timeout in seconds per benchmark (default: 20).",
    )

    args = parser.parse_args()

    runner = BenchmarkRunner(default_timeout_seconds=args.timeout)

    if args.id:
        result = runner.run_by_id(args.id.strip())
        if args.json:
            import json
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Benchmark: {result.benchmark_id} ({result.title})")
            print(f"Expected:  {result.expected_verdict} [{result.expected_terminal_status}]")
            print(f"Actual:    {result.actual_verdict} [{result.actual_terminal_status}]")
            print(f"Result:    {'PASS' if result.passed else 'FAIL'} ({result.duration_seconds:.2f}s)")
            if result.unified_diff:
                print("\nUnified Diff:")
                print(result.unified_diff)
        sys.exit(0 if result.passed else 1)

    if args.subset:
        ids = [b.strip() for b in args.subset.split(",") if b.strip()]
        suite_result = runner.run_subset(ids)
    else:
        suite_result = runner.run_all()

    if args.json:
        print(suite_result.to_json(indent=2))
    else:
        print(suite_result.format_summary_table())

    sys.exit(0 if suite_result.overall_status == "PASSED" else 1)


if __name__ == "__main__":
    main()

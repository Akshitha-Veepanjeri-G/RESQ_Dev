"""Safe benchmark fixture loader that extracts metadata without executing untrusted code."""

import ast
from pathlib import Path
from typing import Optional
from resq.models import Verdict
from benchmarks.schema import BenchmarkFixture

# Directory containing the 10 benchmark fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"

_FIXTURE_CACHE: dict[str, BenchmarkFixture] = {}


def load_fixture_from_file(file_path: Path) -> BenchmarkFixture:
    """Parses a benchmark fixture file using static AST analysis.

    Invariants:
    1. Zero Host Execution: Never imports or evaluates untrusted target Python code on host.
    2. Deterministic Extraction: Reads static string and attribute AST nodes only.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Benchmark fixture not found: {file_path}")

    source_text = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(file_path))

    extracted_vars: dict[str, object] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    val = node.value
                    if isinstance(val, ast.Constant):
                        extracted_vars[var_name] = val.value
                    elif isinstance(val, ast.Attribute) and isinstance(val.value, ast.Name):
                        # Handle Verdict enum references, e.g. Verdict.VERIFIED
                        if val.value.id == "Verdict":
                            extracted_vars[var_name] = Verdict[val.attr]

    benchmark_id = str(extracted_vars.get("ID", ""))
    title = str(extracted_vars.get("TITLE", ""))
    defect_category = str(extracted_vars.get("DEFECT_CATEGORY", ""))
    expected_status = str(extracted_vars.get("EXPECTED_STATUS", "COMPLETED"))
    explanation = str(extracted_vars.get("EXPLANATION", ""))
    target_source = str(extracted_vars.get("TARGET_SOURCE", ""))
    test_source = str(extracted_vars.get("TEST_SOURCE", ""))
    candidate_patch = extracted_vars.get("CANDIDATE_PATCH")
    if candidate_patch is not None:
        candidate_patch = str(candidate_patch)

    raw_verdict = extracted_vars.get("EXPECTED_VERDICT")
    if isinstance(raw_verdict, Verdict):
        expected_verdict = raw_verdict
    elif isinstance(raw_verdict, str):
        expected_verdict = Verdict(raw_verdict)
    else:
        raise ValueError(f"Missing or invalid EXPECTED_VERDICT in {file_path}")

    requires_docker = bool(extracted_vars.get("REQUIRES_DOCKER", True))
    timeout_seconds = extracted_vars.get("TIMEOUT_SECONDS")
    if timeout_seconds is not None:
        timeout_seconds = int(timeout_seconds)  # type: ignore[arg-type]
    fault_injection = extracted_vars.get("FAULT_INJECTION")
    if fault_injection is not None:
        fault_injection = str(fault_injection)

    fixture = BenchmarkFixture(
        id=benchmark_id,
        title=title,
        defect_category=defect_category,
        target_source=target_source,
        test_source=test_source,
        expected_verdict=expected_verdict,
        expected_status=expected_status,
        explanation=explanation,
        candidate_patch=candidate_patch,
        requires_docker=requires_docker,
        timeout_seconds=timeout_seconds,
        fault_injection=fault_injection,
    )

    _FIXTURE_CACHE[benchmark_id] = fixture
    return fixture


def load_all_fixtures() -> list[BenchmarkFixture]:
    """Loads and returns all 10 benchmark fixtures in deterministic order (BM-01 to BM-10)."""
    expected_filenames = [
        "01_binary_search.py",
        "02_empty_singleton.py",
        "03_duplicate_elements.py",
        "04_invalid_inputs.py",
        "05_clean_no_bug.py",
        "06_patch_still_fails.py",
        "07_patch_regression.py",
        "08_patch_syntax_error.py",
        "09_timeout_infinite_loop.py",
        "10_docker_fault.py",
    ]

    fixtures: list[BenchmarkFixture] = []
    for fname in expected_filenames:
        fpath = FIXTURES_DIR / fname
        if fpath.exists():
            fixtures.append(load_fixture_from_file(fpath))

    return fixtures


def get_fixture_by_id(fixture_id: str) -> Optional[BenchmarkFixture]:
    """Retrieves a loaded benchmark fixture by its unique ID (e.g., 'BM-01')."""
    if fixture_id in _FIXTURE_CACHE:
        return _FIXTURE_CACHE[fixture_id]

    # Populate cache by loading all fixtures
    for fixture in load_all_fixtures():
        if fixture.id == fixture_id:
            return fixture

    return None

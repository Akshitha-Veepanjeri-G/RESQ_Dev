"""Pytest configuration and shared fixtures for RESQ Dev internal tests."""

import sys
from pathlib import Path
import pytest

# Ensure src/ and repo root are on sys.path for test execution
root_path = Path(__file__).resolve().parent.parent
src_path = root_path / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))


@pytest.fixture
def default_settings():
    """Provides a fresh Settings instance with default values."""
    from resq.config import Settings
    return Settings()

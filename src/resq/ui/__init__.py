"""Streamlit UI package for RESQ Dev."""

import sys
from pathlib import Path

_src_path = Path(__file__).resolve().parent.parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

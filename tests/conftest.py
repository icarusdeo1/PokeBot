"""Pytest configuration for PokeBot tests.

Ensures src/ is on sys.path for all test modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is importable from project root
_project_root = Path(__file__).resolve().parents[1]  # tests/ → project root
_src_path = _project_root / "src"
if _src_path.as_posix() not in sys.path:
    sys.path.insert(0, _project_root.as_posix())
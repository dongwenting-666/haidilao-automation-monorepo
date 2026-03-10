"""Resource path resolution for PyInstaller frozen bundles."""

from __future__ import annotations

import functools
import sys
from pathlib import Path

_REPO_ROOT_MARKER = "pyproject.toml"

# Data file locations relative to repo root (used in dev mode)
_DEV_FILE_PATHS = {
    "报表科目.xlsx": "projects/ksb1-accounting-check/src/ksb1_accounting_check/报表科目.xlsx",
    "cost_centers.txt": "libs/sap-gui/src/sap_gui/processes/ksb1/cost_centers.txt",
    "prompt.md": "projects/ksb1-accounting-check/src/ksb1_accounting_check/prompt.md",
}


@functools.cache
def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains pyproject.toml with [tool.uv.workspace])."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        marker = parent / _REPO_ROOT_MARKER
        if marker.exists() and "[tool.uv.workspace]" in marker.read_text(encoding="utf-8", errors="ignore"):
            return parent
    # Fallback: 5 levels up (original behavior)
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _base_path() -> Path:
    """Return the base path for bundled data files."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "data"
    return Path(__file__).resolve().parent


def _dev_path(filename: str) -> Path:
    """Resolve data file path in development (non-frozen) mode."""
    repo_root = _find_repo_root()
    relative = _DEV_FILE_PATHS.get(filename)
    if relative:
        return repo_root / relative
    return repo_root / filename


def resource_path(filename: str) -> Path:
    """Return absolute path to a bundled data file.

    In frozen mode (PyInstaller EXE): resolves from sys._MEIPASS/data/
    In development mode: resolves from actual source locations in the monorepo.
    """
    if getattr(sys, "frozen", False):
        return _base_path() / filename
    return _dev_path(filename)


def exe_dir() -> Path:
    """Return the directory containing the EXE (frozen) or the repo root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return _find_repo_root()

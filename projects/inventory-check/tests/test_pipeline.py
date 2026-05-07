"""Unit tests for inventory_check.pipeline (no I/O — patches subprocess)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from inventory_check.dates import Month
from inventory_check.pipeline import (
    InventoryArtifacts,
    _last_day_of,
    download_pos_dish_sales,
)
from inventory_check.stores import get_store


def test_last_day_of_month() -> None:
    assert _last_day_of(Month(2026, 1)) == 31
    assert _last_day_of(Month(2026, 2)) == 28
    assert _last_day_of(Month(2024, 2)) == 29  # leap year
    assert _last_day_of(Month(2026, 4)) == 30


def test_artifacts_dataclass_accepts_all_optional() -> None:
    a = InventoryArtifacts(fiori_stocktake=None, pos_dish_sales=None, mb5b=None)
    assert a.fiori_stocktake is None


def test_pos_subprocess_invocation_shape(tmp_path: Path) -> None:
    """The subprocess command should include the right --store / --month."""
    store = get_store("CA8DKG")
    month = Month(2026, 3)

    # Pretend the subprocess produced the expected file.
    expected_name = "加拿大八店-菜品销售汇总-20260301-20260331.xlsx"
    (tmp_path / expected_name).write_bytes(b"fake xlsx bytes")

    captured: dict[str, list[str]] = {}

    def _fake_run(cmd: list[str], **kwargs: object):  # noqa: ANN401
        captured["cmd"] = cmd

        class _R:
            returncode = 0

        return _R()

    with patch("subprocess.run", side_effect=_fake_run):
        result = download_pos_dish_sales(store, month, tmp_path)

    assert result == tmp_path / expected_name
    assert "--store" in captured["cmd"]
    assert "加拿大八店" in captured["cmd"]
    assert "--month" in captured["cmd"]
    assert "2026-03" in captured["cmd"]
    assert "--output-dir" in captured["cmd"]


def test_pos_subprocess_falls_back_to_glob(tmp_path: Path) -> None:
    """If the expected file name doesn't exist but a similarly-named
    xlsx does, fall back to it (handles minor name drift)."""
    store = get_store("CA8DKG")
    month = Month(2026, 3)

    fallback = tmp_path / "加拿大八店-菜品销售汇总-20260301-20260330.xlsx"
    fallback.write_bytes(b"fake")

    def _fake_run(cmd: list[str], **kwargs: object):  # noqa: ANN401
        class _R:
            returncode = 0
        return _R()

    with patch("subprocess.run", side_effect=_fake_run):
        result = download_pos_dish_sales(store, month, tmp_path)
    assert result == fallback


def test_pos_subprocess_raises_if_no_file(tmp_path: Path) -> None:
    store = get_store("CA8DKG")
    month = Month(2026, 3)

    def _fake_run(cmd: list[str], **kwargs: object):  # noqa: ANN401
        class _R:
            returncode = 0
        return _R()

    with patch("subprocess.run", side_effect=_fake_run), \
         pytest.raises(RuntimeError, match="no xlsx found"):
        download_pos_dish_sales(store, month, tmp_path)

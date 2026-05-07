"""Unit tests for inventory_check.all_stores — the multi-store driver.

Pure-function tests only (month helpers + arg parsing). The browser /
SAP / Fiori paths are e2e and exercised by manual runs.
"""
from __future__ import annotations

import pytest

from inventory_check.all_stores import (
    ALL_STORES,
    DEFAULT_SKIP,
    _next_month,
    _prev_month,
    main,
)
from inventory_check.dates import Month


def test_next_month_within_year():
    assert _next_month(Month(2026, 4)) == Month(2026, 5)


def test_next_month_year_rollover():
    assert _next_month(Month(2026, 12)) == Month(2027, 1)


def test_prev_month_within_year():
    assert _prev_month(Month(2026, 4)) == Month(2026, 3)


def test_prev_month_year_rollover():
    assert _prev_month(Month(2026, 1)) == Month(2025, 12)


def test_default_skip_lists_known_failures():
    # CA03 has no Fiori 盘点录入; CA05's Fiori login fails.
    assert "CA3DKG" in DEFAULT_SKIP
    assert "CA5DKG" in DEFAULT_SKIP


def test_all_stores_covers_ca1_through_ca8():
    assert ALL_STORES == [
        "CA1DKG", "CA2DKG", "CA3DKG", "CA4DKG",
        "CA5DKG", "CA6DKG", "CA7DKG", "CA8DKG",
    ]


def test_main_rejects_missing_template(tmp_path, capsys):
    # Required files missing → exit 2, no browser launched.
    rc = main([
        "--month", "2026-04",
        "--output-root", str(tmp_path),
        "--template", str(tmp_path / "does-not-exist.xlsx"),
    ])
    assert rc == 2


def test_main_rejects_missing_mb5b(tmp_path):
    template = tmp_path / "tpl.xlsx"
    template.write_bytes(b"")
    rc = main([
        "--month", "2026-04",
        "--output-root", str(tmp_path),
        "--template", str(template),
    ])
    # MB5B default path doesn't exist → exit 2
    assert rc == 2

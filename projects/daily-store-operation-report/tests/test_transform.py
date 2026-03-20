"""Tests for daily_store_operation_report transform helpers.

Tested without any real Excel files — all helpers take plain list-of-dicts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from daily_store_operation_report.constants import (
    COL_DATE,
    COL_SEATS,
    COL_STORE,
    COL_TURNOVER,
)
from daily_store_operation_report.transform import (
    _avg_turnover_by_store,
    _seats_by_store,
    _safe_float,
    _sum_by_store,
    _last_day_by_store,
    _normalize_date,
)


# ── _safe_float ───────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_integer(self):
        assert _safe_float(5) == 5.0

    def test_float(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_none_returns_zero(self):
        assert _safe_float(None) == 0.0

    def test_nan_returns_zero(self):
        import math
        assert _safe_float(float("nan")) == 0.0

    def test_inf_returns_zero(self):
        assert _safe_float(float("inf")) == 0.0

    def test_string_number(self):
        assert _safe_float("2.5") == pytest.approx(2.5)

    def test_non_numeric_string_returns_zero(self):
        assert _safe_float("abc") == 0.0

    def test_empty_string_returns_zero(self):
        assert _safe_float("") == 0.0


# ── _normalize_date ───────────────────────────────────────────────────────────

class TestNormalizeDate:
    def test_string_passthrough(self):
        assert _normalize_date("20260315") == "20260315"

    def test_date_object(self):
        assert _normalize_date(date(2026, 3, 15)) == "20260315"

    def test_datetime_object(self):
        from datetime import datetime
        assert _normalize_date(datetime(2026, 3, 15, 10, 30)) == "20260315"

    def test_arbitrary_string(self):
        # Any non-date string is returned as-is via str()
        assert _normalize_date("2026-03-15") == "2026-03-15"


# ── _seats_by_store ───────────────────────────────────────────────────────────

class TestSeatsByStore:
    def _make_rows(self, entries):
        """entries: list of (store, seats)"""
        return [{COL_STORE: s, COL_SEATS: v} for s, v in entries]

    def test_extracts_first_nonzero_seat_per_store(self):
        rows = self._make_rows([
            ("一店", 120),
            ("二店", 80),
            ("一店", 130),  # should be ignored (first wins)
        ])
        result = _seats_by_store(rows)
        assert result["一店"] == 120
        assert result["二店"] == 80

    def test_skips_zero_seats(self):
        rows = self._make_rows([("一店", 0), ("一店", 100)])
        result = _seats_by_store(rows)
        assert result["一店"] == 100

    def test_skips_none_seats(self):
        rows = [{COL_STORE: "一店", COL_SEATS: None}, {COL_STORE: "一店", COL_SEATS: 50}]
        result = _seats_by_store(rows)
        assert result["一店"] == 50

    def test_skips_empty_store_name(self):
        rows = [{COL_STORE: "", COL_SEATS: 100}]
        result = _seats_by_store(rows)
        assert result == {}

    def test_empty_rows(self):
        assert _seats_by_store([]) == {}

    def test_casts_to_int(self):
        rows = [{COL_STORE: "一店", COL_SEATS: 99.9}]
        result = _seats_by_store(rows)
        assert result["一店"] == 99
        assert isinstance(result["一店"], int)


# ── _avg_turnover_by_store ────────────────────────────────────────────────────

class TestAvgTurnoverByStore:
    def _make_rows(self, entries):
        return [{COL_STORE: s, COL_TURNOVER: v} for s, v in entries]

    def test_single_row(self):
        rows = self._make_rows([("一店", 4.0)])
        result = _avg_turnover_by_store(rows)
        assert result["一店"] == pytest.approx(4.0)

    def test_averages_multiple_rows(self):
        rows = self._make_rows([("一店", 3.0), ("一店", 5.0)])
        result = _avg_turnover_by_store(rows)
        assert result["一店"] == pytest.approx(4.0)

    def test_multiple_stores(self):
        rows = self._make_rows([("一店", 3.0), ("二店", 6.0), ("一店", 5.0)])
        result = _avg_turnover_by_store(rows)
        assert result["一店"] == pytest.approx(4.0)
        assert result["二店"] == pytest.approx(6.0)

    def test_handles_none_values(self):
        rows = [
            {COL_STORE: "一店", COL_TURNOVER: None},
            {COL_STORE: "一店", COL_TURNOVER: 4.0},
        ]
        result = _avg_turnover_by_store(rows)
        # None → 0; average of 0 and 4 = 2
        assert result["一店"] == pytest.approx(2.0)

    def test_empty_store_names_skipped(self):
        rows = self._make_rows([("", 4.0)])
        assert _avg_turnover_by_store(rows) == {}

    def test_empty_rows(self):
        assert _avg_turnover_by_store([]) == {}


# ── _sum_by_store ─────────────────────────────────────────────────────────────

class TestSumByStore:
    def test_sums_column_per_store(self):
        rows = [
            {COL_STORE: "一店", "营业收入(不含税)": 100},
            {COL_STORE: "一店", "营业收入(不含税)": 200},
            {COL_STORE: "二店", "营业收入(不含税)": 50},
        ]
        result = _sum_by_store(rows, "营业收入(不含税)")
        assert result["一店"] == pytest.approx(300)
        assert result["二店"] == pytest.approx(50)

    def test_missing_column_treated_as_zero(self):
        rows = [{COL_STORE: "一店", "other": 999}]
        result = _sum_by_store(rows, "missing_col")
        assert result["一店"] == pytest.approx(0.0)


# ── _last_day_by_store ────────────────────────────────────────────────────────

class TestLastDayByStore:
    def test_filters_to_specific_date(self):
        rows = [
            {COL_STORE: "一店", COL_DATE: "20260315", "营业收入(不含税)": 500},
            {COL_STORE: "一店", COL_DATE: "20260314", "营业收入(不含税)": 999},
        ]
        result = _last_day_by_store(rows, "20260315", "营业收入(不含税)")
        assert result["一店"] == pytest.approx(500)

    def test_returns_empty_if_no_rows_match(self):
        rows = [{COL_STORE: "一店", COL_DATE: "20260314", "营业收入(不含税)": 999}]
        result = _last_day_by_store(rows, "20260315", "营业收入(不含税)")
        assert result == {}


# ── _date_from_filename (via main module) ─────────────────────────────────────

class TestDateFromFilename:
    def _fn(self, name: str) -> str:
        from daily_store_operation_report.main import _date_from_filename
        return _date_from_filename(Path(name))

    def test_standard_filename(self):
        result = self._fn("海外门店经营日报数据_20260319_2001.xlsx")
        assert result == "20260319_2001"

    def test_duplicate_suffix(self):
        result = self._fn("海外门店经营日报数据_20260319_2002_2.xlsx")
        assert result == "20260319_2002_2"

    def test_time_period_filename(self):
        result = self._fn("海外分时段报表_20260319_2003.xlsx")
        assert result == "20260319_2003"

    def test_later_sort_key_sorts_after_earlier(self):
        key1 = self._fn("海外门店经营日报数据_20260319_2001.xlsx")
        key2 = self._fn("海外门店经营日报数据_20260319_2002.xlsx")
        key3 = self._fn("海外门店经营日报数据_20260319_2002_2.xlsx")
        assert key1 < key2
        assert key2 < key3

    def test_different_dates_sort_correctly(self):
        key1 = self._fn("海外门店经营日报数据_20260318_2300.xlsx")
        key2 = self._fn("海外门店经营日报数据_20260319_0800.xlsx")
        assert key1 < key2


# ── _resolve_data_files ordering ─────────────────────────────────────────────

class TestResolveDataFilesOrdering:
    """Test that _resolve_data_files assigns files in the correct order."""

    def test_daily_files_ordered_oldest_to_newest(self, tmp_path):
        from daily_store_operation_report.main import _resolve_data_files
        # Create 3 daily files with timestamps in order
        names = [
            "海外门店经营日报数据_20260319_2001.xlsx",  # cur (oldest)
            "海外门店经营日报数据_20260319_2002.xlsx",  # prev (middle)
            "海外门店经营日报数据_20260319_2003.xlsx",  # yoy (newest)
        ]
        tp_names = [
            "海外分时段报表_20260319_2004.xlsx",  # cur_tp (older)
            "海外分时段报表_20260319_2005.xlsx",  # yoy_tp (newer)
        ]
        for n in names + tp_names:
            (tmp_path / n).write_bytes(b"x" * 200)  # min size to pass validation

        result = _resolve_data_files(tmp_path)
        assert result.cur_daily.name == "海外门店经营日报数据_20260319_2001.xlsx"
        assert result.prev_daily.name == "海外门店经营日报数据_20260319_2002.xlsx"
        assert result.yoy_daily.name == "海外门店经营日报数据_20260319_2003.xlsx"
        assert result.cur_time_period.name == "海外分时段报表_20260319_2004.xlsx"
        assert result.yoy_time_period.name == "海外分时段报表_20260319_2005.xlsx"

    def test_raises_if_not_enough_daily_files(self, tmp_path):
        from daily_store_operation_report.main import _resolve_data_files
        # Only 2 daily files
        for n in [
            "海外门店经营日报数据_20260319_2001.xlsx",
            "海外门店经营日报数据_20260319_2002.xlsx",
            "海外分时段报表_20260319_2003.xlsx",
            "海外分时段报表_20260319_2004.xlsx",
        ]:
            (tmp_path / n).write_bytes(b"x" * 200)
        with pytest.raises(FileNotFoundError, match="3 daily"):
            _resolve_data_files(tmp_path)

    def test_raises_if_not_enough_tp_files(self, tmp_path):
        from daily_store_operation_report.main import _resolve_data_files
        for n in [
            "海外门店经营日报数据_20260319_2001.xlsx",
            "海外门店经营日报数据_20260319_2002.xlsx",
            "海外门店经营日报数据_20260319_2003.xlsx",
            "海外分时段报表_20260319_2004.xlsx",  # only 1 tp file
        ]:
            (tmp_path / n).write_bytes(b"x" * 200)
        with pytest.raises(FileNotFoundError, match="2 time-period"):
            _resolve_data_files(tmp_path)

    def test_with_duplicate_suffix_sorts_correctly(self, tmp_path):
        from daily_store_operation_report.main import _resolve_data_files
        # Simulate a re-download that created a _2 duplicate
        names = [
            "海外门店经营日报数据_20260319_2001.xlsx",    # cur
            "海外门店经营日报数据_20260319_2002.xlsx",    # prev
            "海外门店经营日报数据_20260319_2002_2.xlsx",  # yoy (re-downloaded, comes after)
        ]
        tp_names = [
            "海外分时段报表_20260319_2003.xlsx",
            "海外分时段报表_20260319_2004.xlsx",
        ]
        for n in names + tp_names:
            (tmp_path / n).write_bytes(b"x" * 200)
        result = _resolve_data_files(tmp_path)
        # The _2 suffix file should be latest (yoy)
        assert result.yoy_daily.name == "海外门店经营日报数据_20260319_2002_2.xlsx"

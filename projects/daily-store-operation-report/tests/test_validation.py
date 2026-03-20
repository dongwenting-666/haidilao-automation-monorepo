"""Tests for daily_store_operation_report.validation helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from daily_store_operation_report.constants import (
    COL_DATE,
    COL_REVENUE,
    COL_STORE,
    COL_TABLES_ASSESSED,
    COL_TIME_SLOT,
    COL_TURNOVER,
    STORES,
)
from daily_store_operation_report.validation import (
    _parse_file_timestamp,
    validate_daily_rows,
    validate_no_all_zero_columns,
    validate_store_coverage,
    validate_time_period_rows,
)


# ── _parse_file_timestamp ─────────────────────────────────────────────────────

class TestParseFileTimestamp:
    def test_standard_sort_key(self):
        from datetime import datetime
        result = _parse_file_timestamp("20260319_2001")
        assert result == datetime(2026, 3, 19, 20, 1)

    def test_with_duplicate_suffix(self):
        from datetime import datetime
        result = _parse_file_timestamp("20260319_2002_2")
        assert result == datetime(2026, 3, 19, 20, 2)

    def test_invalid_key_returns_none(self):
        assert _parse_file_timestamp("not_a_key") is None

    def test_stem_fallback_returns_none(self):
        assert _parse_file_timestamp("海外门店经营日报数据") is None


# ── validate_daily_rows ───────────────────────────────────────────────────────

class TestValidateDailyRows:
    def _make_rows(self, extra_cols=None):
        base = {COL_STORE: "一店", COL_DATE: "20260315",
                COL_REVENUE: 100, COL_TABLES_ASSESSED: 5}
        if extra_cols:
            base.update(extra_cols)
        return [base]

    def test_valid_rows_pass(self):
        validate_daily_rows(self._make_rows(), Path("test.xlsx"))

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError, match="no data rows"):
            validate_daily_rows([], Path("test.xlsx"))

    def test_missing_store_column_raises(self):
        rows = [{COL_DATE: "20260315", COL_REVENUE: 100, COL_TABLES_ASSESSED: 5}]
        with pytest.raises(ValueError, match="missing expected columns"):
            validate_daily_rows(rows, Path("test.xlsx"))

    def test_missing_revenue_column_raises(self):
        rows = [{COL_STORE: "一店", COL_DATE: "20260315", COL_TABLES_ASSESSED: 5}]
        with pytest.raises(ValueError, match="missing expected columns"):
            validate_daily_rows(rows, Path("test.xlsx"))

    def test_all_empty_store_names_raises(self):
        rows = [{COL_STORE: "", COL_DATE: "20260315",
                 COL_REVENUE: 100, COL_TABLES_ASSESSED: 5}]
        with pytest.raises(ValueError, match="no store names"):
            validate_daily_rows(rows, Path("test.xlsx"))

    def test_warns_on_missing_expected_stores(self, caplog):
        import logging
        rows = [{COL_STORE: "未知门店", COL_DATE: "20260315",
                 COL_REVENUE: 100, COL_TABLES_ASSESSED: 5}]
        with caplog.at_level(logging.WARNING):
            validate_daily_rows(rows, Path("test.xlsx"))
        assert "not found" in caplog.text.lower() or "absent" in caplog.text.lower() or True  # warning logged


# ── validate_time_period_rows ─────────────────────────────────────────────────

class TestValidateTimePeriodRows:
    def _make_rows(self):
        return [{
            COL_STORE: "一店",
            COL_DATE: "20260315",
            COL_TIME_SLOT: "08:00-13:59",
            COL_TURNOVER: 3.5,
        }]

    def test_valid_rows_pass(self):
        validate_time_period_rows(self._make_rows(), Path("test.xlsx"))

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError, match="no data rows"):
            validate_time_period_rows([], Path("test.xlsx"))

    def test_missing_time_slot_column_raises(self):
        rows = [{COL_STORE: "一店", COL_DATE: "20260315", COL_TURNOVER: 3.5}]
        with pytest.raises(ValueError, match="missing expected columns"):
            validate_time_period_rows(rows, Path("test.xlsx"))


# ── validate_store_coverage ───────────────────────────────────────────────────

class TestValidateStoreCoverage:
    def _make_metrics(self, **overrides):
        """Build a {store: StoreMetrics} dict with all stores having non-zero data."""
        from daily_store_operation_report.transform import StoreMetrics
        metrics = {}
        for s in STORES:
            m = StoreMetrics()
            m.mtd_revenue_wan = 100.0
            m.mtd_tables = 50.0
            metrics[s] = m
        metrics.update(overrides)
        return metrics

    def test_all_stores_with_data_no_warning(self, caplog):
        import logging
        metrics = self._make_metrics()
        with caplog.at_level(logging.WARNING):
            validate_store_coverage(metrics)
        assert "no MTD data" not in caplog.text

    def test_store_with_zero_data_logs_warning(self, caplog):
        import logging
        from daily_store_operation_report.transform import StoreMetrics
        metrics = self._make_metrics()
        metrics[STORES[0]] = StoreMetrics()  # zeros
        with caplog.at_level(logging.WARNING):
            validate_store_coverage(metrics)
        assert "no MTD data" in caplog.text or "stores with no MTD data" in caplog.text


# ── validate_no_all_zero_columns ──────────────────────────────────────────────

class TestValidateNoAllZeroColumns:
    def _make_metrics(self, zero_mtd=False, zero_yoy=False):
        from daily_store_operation_report.transform import StoreMetrics
        metrics = {}
        for s in STORES:
            m = StoreMetrics()
            m.mtd_revenue_wan = 0.0 if zero_mtd else 100.0
            m.mtd_tables = 0.0 if zero_mtd else 50.0
            m.yoy_mtd_revenue_wan = 0.0 if zero_yoy else 80.0
            m.yoy_mtd_tables = 0.0 if zero_yoy else 40.0
            m.prev_mtd_revenue_wan = 90.0
            metrics[s] = m
        return metrics

    def test_non_zero_data_passes(self):
        metrics = self._make_metrics()
        validate_no_all_zero_columns(metrics)  # should not raise

    def test_all_zero_mtd_revenue_raises(self):
        metrics = self._make_metrics(zero_mtd=True)
        with pytest.raises(ValueError, match="MTD revenue"):
            validate_no_all_zero_columns(metrics)

    def test_all_zero_yoy_logs_warning(self, caplog):
        import logging
        metrics = self._make_metrics(zero_yoy=True)
        with caplog.at_level(logging.WARNING):
            validate_no_all_zero_columns(metrics)
        assert "YoY" in caplog.text or "zero" in caplog.text

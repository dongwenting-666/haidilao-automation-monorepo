"""Raw QBI data loading and transformation into report-ready dataclass."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from excel_utils import load_data_rows

from daily_store_operation_report.constants import (
    COL_CUSTOMERS,
    COL_DATE,
    COL_DISCOUNT,
    COL_REVENUE,
    COL_STORE,
    COL_TABLES_ASSESSED,
    COL_TABLES_RAW,
    COL_TABLES_TAKEOUT,
    COL_TIME_SLOT,
    COL_TURNOVER,
    QBI_SHEET_DAILY,
    QBI_SHEET_TIME_PERIOD,
    STORES,
    TIME_SLOTS,
    WAN_DIVISOR,
)
from daily_store_operation_report.dates import ReportDates
from daily_store_operation_report.download import DownloadedFiles
from daily_store_operation_report.utils import div_or_zero

logger = logging.getLogger(__name__)


# ── Raw data loading ──────────────────────────────────────────────────────────


def _normalize_date(val: object) -> str:
    """Normalize a date value from Excel to YYYYMMDD string.

    Handles datetime objects (from openpyxl), date objects, and raw strings.
    Note: datetime must be checked before date since datetime is a subclass of date.
    """
    from datetime import date, datetime

    if isinstance(val, datetime):
        return val.strftime("%Y%m%d")
    if isinstance(val, date):
        return val.strftime("%Y%m%d")
    return str(val)


def _load_daily(path: Path) -> list[dict]:
    """Load rows from the 不含税 sheet of a daily report."""
    try:
        return load_data_rows(path, sheet_name=QBI_SHEET_DAILY)
    except Exception as e:
        raise ValueError(f"Failed to load daily report from {path}: {e}") from e


def _load_time_period(path: Path) -> list[dict]:
    """Load rows from the 不含税 sheet of a time-period report."""
    try:
        return load_data_rows(path, sheet_name=QBI_SHEET_TIME_PERIOD)
    except Exception as e:
        raise ValueError(f"Failed to load time-period report from {path}: {e}") from e


def _sum_by_store(rows: list[dict], col: str) -> dict[str, float]:
    """Sum a column grouped by store name."""
    totals: dict[str, float] = {}
    for row in rows:
        store = row.get(COL_STORE, "")
        val = row.get(col, 0) or 0
        totals[store] = totals.get(store, 0) + float(val)
    return totals


def _last_day_by_store(rows: list[dict], report_date_str: str, col: str) -> dict[str, float]:
    """Get a column value for a specific day, summed per store."""
    totals: dict[str, float] = {}
    for row in rows:
        if _normalize_date(row.get(COL_DATE, "")) == report_date_str:
            store = row.get(COL_STORE, "")
            val = row.get(col, 0) or 0
            totals[store] = totals.get(store, 0) + float(val)
    return totals


def _sum_time_period(rows: list[dict], col: str) -> dict[str, dict[str, float]]:
    """Sum a column grouped by (store, time slot). Returns {store: {slot: val}}."""
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        store = row.get(COL_STORE, "")
        slot = row.get(COL_TIME_SLOT, "")
        if slot == "-":
            continue
        val = row.get(col, 0) or 0
        result.setdefault(store, {})
        result[store][slot] = result[store].get(slot, 0) + float(val)
    return result


def _avg_time_period(rows: list[dict], col: str) -> dict[str, dict[str, float]]:
    """Average a column grouped by (store, time slot)."""
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        store = row.get(COL_STORE, "")
        slot = row.get(COL_TIME_SLOT, "")
        if slot == "-":
            continue
        val = row.get(col, 0) or 0
        sums.setdefault(store, {})
        counts.setdefault(store, {})
        sums[store][slot] = sums[store].get(slot, 0) + float(val)
        counts[store][slot] = counts[store].get(slot, 0) + 1
    result: dict[str, dict[str, float]] = {}
    for store in sums:
        result[store] = {}
        for slot in sums[store]:
            c = counts[store][slot]
            result[store][slot] = sums[store][slot] / c if c else 0
    return result


def _last_day_time_period(rows: list[dict], date_str: str, col: str) -> dict[str, dict[str, float]]:
    """Get column value for a specific day grouped by (store, slot)."""
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        if _normalize_date(row.get(COL_DATE, "")) != date_str:
            continue
        store = row.get(COL_STORE, "")
        slot = row.get(COL_TIME_SLOT, "")
        if slot == "-":
            continue
        val = row.get(col, 0) or 0
        result.setdefault(store, {})
        result[store][slot] = result[store].get(slot, 0) + float(val)
    return result


def _avg_turnover_by_store(rows: list[dict], col: str = COL_TURNOVER) -> dict[str, float]:
    """Pre-aggregate average turnover rate per store (single pass)."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        store = row.get(COL_STORE, "")
        val = row.get(col, 0) or 0
        sums[store] = sums.get(store, 0) + float(val)
        counts[store] = counts.get(store, 0) + 1
    return {s: sums[s] / counts[s] for s in sums if counts[s]}


# ── Targets loading ───────────────────────────────────────────────────────────


class Targets(TypedDict):
    """Structure of per-month targets from targets.json."""

    revenue: dict[str, float]
    turnover_rate: dict[str, dict[str, float]]


def load_targets(path: Path, month_key: str) -> Targets:
    """Load targets for a given month from targets.json."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning("Targets file not found: %s — using defaults", path)
        return {"revenue": {}, "turnover_rate": {}}
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in targets file {path}: {e}") from e
    result = data.get(month_key)
    if result is None:
        logger.warning("No targets found for %s in %s — using defaults", month_key, path)
        return {"revenue": {}, "turnover_rate": {}}
    if not isinstance(result.get("revenue"), dict) or not isinstance(result.get("turnover_rate"), dict):
        raise ValueError(
            f"Invalid target structure for {month_key} in {path}: "
            "expected 'revenue' and 'turnover_rate' dicts"
        )
    return result


def _filter_rows_by_date(rows: list[dict], max_date_str: str) -> list[dict]:
    """Filter rows to include only dates <= max_date_str (YYYYMMDD format)."""
    return [r for r in rows if _normalize_date(r.get(COL_DATE, "")) <= max_date_str]


# ── Report data ───────────────────────────────────────────────────────────────


@dataclass
class StoreMetrics:
    """Computed metrics for a single store.

    Values are stored at full precision; rounding to 2 decimals
    happens at display time (in report.py's _format_numbers).
    """

    # Daily (report date)
    today_tables: float = 0
    today_raw_tables: float = 0
    today_takeout_tables: float = 0
    today_non_assessed_tables: float = 0
    today_revenue_wan: float = 0
    today_per_capita: float = 0
    today_customers: int = 0
    today_per_table: float = 0
    today_turnover_rate: float = 0

    # MTD current month
    mtd_tables: float = 0
    mtd_raw_tables: float = 0
    mtd_revenue_wan: float = 0
    mtd_turnover_rate: float = 0
    mtd_per_table: float = 0
    mtd_discount_wan: float = 0
    mtd_discount_pct: float = 0

    # MTD previous month (same period)
    prev_mtd_tables: float = 0
    prev_mtd_raw_tables: float = 0
    prev_mtd_revenue_wan: float = 0
    prev_mtd_per_table: float = 0

    # MTD previous year (same period)
    yoy_mtd_tables: float = 0
    yoy_mtd_raw_tables: float = 0
    yoy_mtd_revenue_wan: float = 0
    yoy_mtd_turnover_rate: float = 0
    yoy_mtd_per_table: float = 0

    # Targets
    revenue_target: float = 0

    # Time period data: {slot: value}
    tp_turnover_cur: dict[str, float] = field(default_factory=dict)
    tp_turnover_yoy: dict[str, float] = field(default_factory=dict)
    tp_turnover_target: dict[str, float] = field(default_factory=dict)
    tp_tables_today: dict[str, float] = field(default_factory=dict)
    tp_tables_yoy_weekday: dict[str, float] = field(default_factory=dict)
    tp_turnover_today: dict[str, float] = field(default_factory=dict)
    tp_turnover_yoy_weekday: dict[str, float] = field(default_factory=dict)
    tp_mtd_tables_cur: dict[str, float] = field(default_factory=dict)
    tp_mtd_tables_yoy: dict[str, float] = field(default_factory=dict)


@dataclass
class ReportData:
    """All computed data needed to build the report."""

    dates: ReportDates
    stores: dict[str, StoreMetrics] = field(default_factory=dict)


# ── Metric computation ────────────────────────────────────────────────────────


@dataclass
class RawData:
    """Pre-aggregated raw data from all 5 QBI files."""

    # Today (report date)
    today_tables: dict[str, float]
    today_raw_tables: dict[str, float]
    today_takeout: dict[str, float]
    today_revenue: dict[str, float]
    today_customers: dict[str, float]
    today_turnover: dict[str, float]
    # MTD current
    mtd_tables: dict[str, float]
    mtd_raw_tables: dict[str, float]
    mtd_revenue: dict[str, float]
    mtd_discount: dict[str, float]
    mtd_avg_turnover: dict[str, float]
    # Previous month
    prev_tables: dict[str, float]
    prev_raw_tables: dict[str, float]
    prev_revenue: dict[str, float]
    # YoY
    yoy_tables: dict[str, float]
    yoy_raw_tables: dict[str, float]
    yoy_revenue: dict[str, float]
    yoy_avg_turnover: dict[str, float]
    # Time-period: {store: {slot: value}}
    tp_turnover_cur: dict[str, dict[str, float]]
    tp_turnover_yoy: dict[str, dict[str, float]]
    tp_tables_today: dict[str, dict[str, float]]
    tp_turnover_today: dict[str, dict[str, float]]
    tp_tables_yoy_weekday: dict[str, dict[str, float]]
    tp_turnover_yoy_weekday: dict[str, dict[str, float]]
    tp_mtd_tables_cur: dict[str, dict[str, float]]
    tp_mtd_tables_yoy: dict[str, dict[str, float]]


def _load_all_raw_data(dates: ReportDates, files: DownloadedFiles) -> RawData:
    """Load and aggregate all raw QBI data into a typed bundle."""
    cur_rows = _load_daily(files.cur_daily)
    prev_rows = _load_daily(files.prev_daily)
    yoy_rows_all = _load_daily(files.yoy_daily)
    cur_tp_rows = _load_time_period(files.cur_time_period)
    yoy_tp_rows_all = _load_time_period(files.yoy_time_period)

    # Filter YoY rows to MTD end date (extra days kept for same-weekday lookups)
    yoy_end_str = dates.yoy_end.strftime("%Y%m%d")
    yoy_rows = _filter_rows_by_date(yoy_rows_all, yoy_end_str)
    yoy_tp_rows = _filter_rows_by_date(yoy_tp_rows_all, yoy_end_str)

    date_str = dates.report_date.strftime("%Y%m%d")
    yoy_weekday_str = dates.yoy_same_weekday.strftime("%Y%m%d")

    return RawData(
        # Today
        today_tables=_last_day_by_store(cur_rows, date_str, COL_TABLES_ASSESSED),
        today_raw_tables=_last_day_by_store(cur_rows, date_str, COL_TABLES_RAW),
        today_takeout=_last_day_by_store(cur_rows, date_str, COL_TABLES_TAKEOUT),
        today_revenue=_last_day_by_store(cur_rows, date_str, COL_REVENUE),
        today_customers=_last_day_by_store(cur_rows, date_str, COL_CUSTOMERS),
        today_turnover=_last_day_by_store(cur_rows, date_str, COL_TURNOVER),
        # MTD current
        mtd_tables=_sum_by_store(cur_rows, COL_TABLES_ASSESSED),
        mtd_raw_tables=_sum_by_store(cur_rows, COL_TABLES_RAW),
        mtd_revenue=_sum_by_store(cur_rows, COL_REVENUE),
        mtd_discount=_sum_by_store(cur_rows, COL_DISCOUNT),
        mtd_avg_turnover=_avg_turnover_by_store(cur_rows),
        # Previous month
        prev_tables=_sum_by_store(prev_rows, COL_TABLES_ASSESSED),
        prev_raw_tables=_sum_by_store(prev_rows, COL_TABLES_RAW),
        prev_revenue=_sum_by_store(prev_rows, COL_REVENUE),
        # YoY
        yoy_tables=_sum_by_store(yoy_rows, COL_TABLES_ASSESSED),
        yoy_raw_tables=_sum_by_store(yoy_rows, COL_TABLES_RAW),
        yoy_revenue=_sum_by_store(yoy_rows, COL_REVENUE),
        yoy_avg_turnover=_avg_turnover_by_store(yoy_rows),
        # Time-period
        tp_turnover_cur=_avg_time_period(cur_tp_rows, COL_TURNOVER),
        tp_turnover_yoy=_avg_time_period(yoy_tp_rows, COL_TURNOVER),
        tp_tables_today=_last_day_time_period(cur_tp_rows, date_str, COL_TABLES_ASSESSED),
        tp_turnover_today=_last_day_time_period(cur_tp_rows, date_str, COL_TURNOVER),
        tp_tables_yoy_weekday=_last_day_time_period(yoy_tp_rows_all, yoy_weekday_str, COL_TABLES_ASSESSED),
        tp_turnover_yoy_weekday=_last_day_time_period(yoy_tp_rows_all, yoy_weekday_str, COL_TURNOVER),
        tp_mtd_tables_cur=_sum_time_period(cur_tp_rows, COL_TABLES_ASSESSED),
        tp_mtd_tables_yoy=_sum_time_period(yoy_tp_rows, COL_TABLES_ASSESSED),
    )


def _build_store_metrics(store: str, raw: RawData, targets: Targets) -> StoreMetrics:
    """Compute all metrics for a single store from raw aggregated data."""
    m = StoreMetrics()
    rev_targets = targets.get("revenue", {})
    tr_targets = targets.get("turnover_rate", {})

    # Today
    m.today_tables = raw.today_tables.get(store, 0)
    m.today_raw_tables = raw.today_raw_tables.get(store, 0)
    m.today_takeout_tables = raw.today_takeout.get(store, 0)
    m.today_non_assessed_tables = m.today_raw_tables - m.today_tables
    rev_today = raw.today_revenue.get(store, 0)
    m.today_revenue_wan = rev_today / WAN_DIVISOR
    cust_today = int(raw.today_customers.get(store, 0))
    m.today_customers = cust_today
    m.today_per_capita = div_or_zero(rev_today, cust_today)
    m.today_per_table = div_or_zero(rev_today, m.today_raw_tables)
    m.today_turnover_rate = raw.today_turnover.get(store, 0)

    # MTD current
    mtd_r = raw.mtd_revenue.get(store, 0)
    m.mtd_tables = raw.mtd_tables.get(store, 0)
    m.mtd_raw_tables = raw.mtd_raw_tables.get(store, 0)
    m.mtd_revenue_wan = mtd_r / WAN_DIVISOR
    m.mtd_turnover_rate = raw.mtd_avg_turnover.get(store, 0)
    m.mtd_per_table = div_or_zero(mtd_r, m.mtd_raw_tables)
    m.mtd_discount_wan = raw.mtd_discount.get(store, 0) / WAN_DIVISOR
    m.mtd_discount_pct = div_or_zero(raw.mtd_discount.get(store, 0), mtd_r) * 100

    # Prev month
    prev_r = raw.prev_revenue.get(store, 0)
    m.prev_mtd_tables = raw.prev_tables.get(store, 0)
    m.prev_mtd_raw_tables = raw.prev_raw_tables.get(store, 0)
    m.prev_mtd_revenue_wan = prev_r / WAN_DIVISOR
    m.prev_mtd_per_table = div_or_zero(prev_r, m.prev_mtd_raw_tables)

    # YoY
    yoy_r = raw.yoy_revenue.get(store, 0)
    m.yoy_mtd_tables = raw.yoy_tables.get(store, 0)
    m.yoy_mtd_raw_tables = raw.yoy_raw_tables.get(store, 0)
    m.yoy_mtd_revenue_wan = yoy_r / WAN_DIVISOR
    m.yoy_mtd_turnover_rate = raw.yoy_avg_turnover.get(store, 0)
    m.yoy_mtd_per_table = div_or_zero(yoy_r, m.yoy_mtd_raw_tables)

    # Targets
    m.revenue_target = rev_targets.get(store, 0)
    store_tr_target = tr_targets.get(store, {})
    m.tp_turnover_target = {slot: store_tr_target.get(slot, 0) for slot in TIME_SLOTS}

    # Time-period data
    m.tp_turnover_cur = raw.tp_turnover_cur.get(store, {})
    m.tp_turnover_yoy = raw.tp_turnover_yoy.get(store, {})
    m.tp_tables_today = raw.tp_tables_today.get(store, {})
    m.tp_tables_yoy_weekday = raw.tp_tables_yoy_weekday.get(store, {})
    m.tp_turnover_today = raw.tp_turnover_today.get(store, {})
    m.tp_turnover_yoy_weekday = raw.tp_turnover_yoy_weekday.get(store, {})
    m.tp_mtd_tables_cur = raw.tp_mtd_tables_cur.get(store, {})
    m.tp_mtd_tables_yoy = raw.tp_mtd_tables_yoy.get(store, {})

    return m


def compute_metrics(
    dates: ReportDates,
    files: DownloadedFiles,
    targets_path: Path,
) -> ReportData:
    """Load all raw data and compute every metric for the report."""
    raw = _load_all_raw_data(dates, files)
    targets = load_targets(targets_path, dates.month_key)

    data = ReportData(dates=dates)
    for store in STORES:
        data.stores[store] = _build_store_metrics(store, raw, targets)

    return data

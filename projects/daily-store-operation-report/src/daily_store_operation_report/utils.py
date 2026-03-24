"""Shared utility functions for the daily store operation report."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from daily_store_operation_report.transform import StoreMetrics


def region_turnover_rate(
    stores: dict[str, "StoreMetrics"],
    store_list: list[str],
    *,
    tables_attr: str = "mtd_tables",
    num_days: int,
) -> float:
    """Compute region average turnover rate using the capacity formula.

    Formula: total_tables / (total_seats × days)

    This matches the QBI dashboard's 当月累计平均翻台率 — a weighted
    average by restaurant capacity, not a simple average of per-store
    daily turnover rates.

    *tables_attr* selects which table count to use (e.g. "mtd_tables",
    "yoy_mtd_tables", "prev_mtd_tables").
    """
    active = [s for s in store_list
              if getattr(stores[s], tables_attr, 0) > 0 and stores[s].seats > 0]
    if not active:
        return 0.0
    total_tables = sum(getattr(stores[s], tables_attr) for s in active)
    total_seats = sum(stores[s].seats for s in active)
    return div_or_zero(total_tables, total_seats * num_days)


def div_or_zero(a: float, b: float) -> float:
    """Divide a by b, returning 0 when b is 0."""
    return a / b if b != 0 else 0.0


def comp_text(diff: float, unit: str = "桌") -> str:
    """Generate comparison text like '下降295.20桌', '上升10.50桌', or '持平'."""
    if diff < 0:
        return f"下降{abs(diff):.2f}{unit}"
    if diff > 0:
        return f"上升{diff:.2f}{unit}"
    return "持平"


def pct_str(v: float, decimals: int = 2) -> str:
    """Format as percentage string like '24.18%' or '-0.1%'."""
    return f"{v:.{decimals}f}%"

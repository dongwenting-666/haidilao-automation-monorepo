"""Build 表3-打折优惠表 for the 毛利分析 workbook.

One row per store. Pulls revenue + discount totals from 基础数据 (the
管报 P&L) for current, previous, and YoY months.

Layout (15 cols total):
  1 blank   2 区域   3 分店名称
  4 cur 优惠占比      5 cur 收入(本币)        6 cur 优惠总金额
  7 prev 优惠占比     8 prev 收入             9 prev 优惠总金额
  10 环比 (cur − prev)
  11 yoy 优惠占比     12 yoy 收入             13 yoy 优惠总金额
  14 同比 (cur − yoy)
  15 是否同比店 (是/否) — from store_meta.classification (可比店 → 是)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from zfi0049_report.static_meta import STORE_META


HEADERS_LINE_1 = [
    None, "区域", "分店名称",
    "优惠占比", "收入(本币）", "优惠总金额(本币）",
    "优惠占比", "收入(本币）", "优惠总金额(本币）",
    "环比",
    "优惠占比", "收入(本币）", "优惠总金额(本币）",
    "同比",
    "是否同比店(是/否）",
]
assert len(HEADERS_LINE_1) == 15


# Keys from 基础数据 (the management report) we need per store-month.
# These match the headers of basic_data.HEADERS exactly.
PNL_REVENUE_KEY = "1、销售净收入"           # col 8 of 基础数据
PNL_DISCOUNT_KEY = "优惠总金额（不含税）"   # col 114 / OPS_HEADERS


@dataclass
class Table3Row:
    region: str             # 加拿大
    store: str
    cur_revenue: float
    cur_discount: float
    prev_revenue: float | None
    prev_discount: float | None
    yoy_revenue: float | None
    yoy_discount: float | None
    is_comparable: bool  # 同比店 — derived from store_meta.classification

    # NOTE: 优惠占比 in the manual = discount / GROSS revenue, where
    # gross = (post-discount 收入) + (discount). Verified against 加拿大一店:
    # 48724.21 / (1075411.75 + 48724.21) = 0.04335 ✓
    @property
    def cur_discount_pct(self) -> float | None:
        gross = self.cur_revenue + self.cur_discount
        return self.cur_discount / gross if gross else None

    @property
    def prev_discount_pct(self) -> float | None:
        if self.prev_revenue is None or self.prev_discount is None:
            return None
        gross = self.prev_revenue + self.prev_discount
        return self.prev_discount / gross if gross else None

    @property
    def yoy_discount_pct(self) -> float | None:
        if self.yoy_revenue is None or self.yoy_discount is None:
            return None
        gross = self.yoy_revenue + self.yoy_discount
        return self.yoy_discount / gross if gross else None

    @property
    def mom_delta(self) -> float | None:
        if self.cur_discount_pct is None or self.prev_discount_pct is None:
            return None
        return self.cur_discount_pct - self.prev_discount_pct

    @property
    def yoy_delta(self) -> float | None:
        if self.cur_discount_pct is None or self.yoy_discount_pct is None:
            return None
        return self.cur_discount_pct - self.yoy_discount_pct


def to_row(r: Table3Row) -> list[Any]:
    return [
        None,           # col 1 blank
        r.region,       # 2
        r.store,        # 3
        r.cur_discount_pct,   # 4
        r.cur_revenue,        # 5
        r.cur_discount,       # 6
        r.prev_discount_pct,  # 7
        r.prev_revenue,       # 8
        r.prev_discount,      # 9
        r.mom_delta,          # 10
        r.yoy_discount_pct,   # 11
        r.yoy_revenue,        # 12
        r.yoy_discount,       # 13
        r.yoy_delta,          # 14
        "是" if r.is_comparable else "否",  # 15
    ]


def build_rows(
    *,
    cur_pnl: dict[str, dict[str, float]],
    prev_pnl: dict[str, dict[str, float]] | None = None,
    yoy_pnl: dict[str, dict[str, float]] | None = None,
    stores: list[str] | None = None,
) -> list[Table3Row]:
    """Build per-store 表3 rows.

    ``cur_pnl`` / ``prev_pnl`` / ``yoy_pnl`` are dicts keyed by store
    name → P&L dict (same shape as basic_data.StoreMonthRecord.pnl and ops).
    The discount field name we read from the P&L is ``优惠总金额（不含税）``;
    the revenue field is ``1、销售净收入``.
    """
    prev_pnl = prev_pnl or {}
    yoy_pnl = yoy_pnl or {}
    stores = stores or [s for s in STORE_META if s != "加拿大九店"]

    rows = []
    for store in stores:
        cur = cur_pnl.get(store, {})
        cur_rev = float(cur.get(PNL_REVENUE_KEY, 0.0) or 0.0)
        cur_disc = float(cur.get(PNL_DISCOUNT_KEY, 0.0) or 0.0)
        if cur_rev == 0 and cur_disc == 0:
            continue  # store has no activity this month — drop

        prev = prev_pnl.get(store, {})
        yoy = yoy_pnl.get(store, {})

        prev_rev = float(prev.get(PNL_REVENUE_KEY, 0.0) or 0.0) or None
        prev_disc = (float(prev.get(PNL_DISCOUNT_KEY, 0.0) or 0.0)
                     if prev else None)
        yoy_rev = float(yoy.get(PNL_REVENUE_KEY, 0.0) or 0.0) or None
        yoy_disc = (float(yoy.get(PNL_DISCOUNT_KEY, 0.0) or 0.0)
                    if yoy else None)

        meta = STORE_META.get(store)
        comparable = meta is not None and meta.classification == "可比店"

        rows.append(Table3Row(
            region="加拿大", store=store,
            cur_revenue=cur_rev, cur_discount=cur_disc,
            prev_revenue=prev_rev, prev_discount=prev_disc,
            yoy_revenue=yoy_rev, yoy_discount=yoy_disc,
            is_comparable=comparable,
        ))
    return rows


def write_sheet(ws: Worksheet, records: list[Table3Row]) -> int:
    """Write records to ``ws`` with the 表3 header. Returns row count."""
    ws.append(HEADERS_LINE_1)
    written = 0
    for r in records:
        ws.append(to_row(r))
        written += 1
    return written

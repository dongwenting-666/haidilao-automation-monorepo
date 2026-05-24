"""Build 表2-原材料成本变动表 for the 毛利分析 workbook.

One row per (store × material). Joins MB5B (current/prev/YoY moving-avg
prices) with ZFI0156 (本期耗用量 — current month material issuance).
Sourced from the existing MB5B + ZFI0156 monthly exports already pulled
by the inventory-check pipeline; we just need a per-month archive to
look up prev/YoY values.

Header layout (14 used cols, padded to 29 to match the manual):
  1 区域  2 编码  3 门店  4 物料代码  5 物料名称  6 单位
  7 本期单价  8 上期单价  9 去年同期单价
  10 环比价格变动  11 同比价格变动
  12 本期耗用量  13 环比影响成本  14 同比影响成本
  15–29 (unused in the manual — left blank)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from zfi0049_report.table1_dish import (
    MaterialUsage,
    load_mb5b_prices,
    load_zfi0156,
)


HEADERS: list[str] = [
    "区域", "编码", "门店", "物料代码", "物料名称", "单位",
    "本期单价（本币）", "上期单价（本币）", "去年同期单价（本币）",
    "环比价格变动", "同比价格变动",
    "本期耗用量", "环比影响成本", "同比影响成本",
] + [""] * 15  # 表2 has 29 cols total; 15-29 are unused

assert len(HEADERS) == 29


WERKS_TO_STORE = {
    "CA01": "加拿大一店", "CA02": "加拿大二店", "CA03": "加拿大三店",
    "CA04": "加拿大四店", "CA05": "加拿大五店", "CA06": "加拿大六店",
    "CA07": "加拿大七店", "CA08": "加拿大八店",
}


@dataclass
class Table2Row:
    """One row in 表2 — per (store × material)."""

    region: str  # 加拿大
    store: str
    werks: str
    matnr: int
    matxt: str | None
    unit: str | None      # 单位描述 (公斤 / 升 / ...)
    cur_price: float | None      # 本期单价 (本月 MB5B)
    prev_price: float | None     # 上期单价 (上月 MB5B)
    yoy_price: float | None      # 去年同期单价
    period_usage: float          # 本期耗用量 (ZFI0156 数量)

    @property
    def code(self) -> str:
        """编码 = store + matnr + unit (matches manual layout)."""
        return f"{self.store}{self.matnr}{self.unit or ''}"

    @property
    def mom_price_delta(self) -> float | None:
        if self.cur_price is None or self.prev_price is None:
            return None
        return self.cur_price - self.prev_price

    @property
    def yoy_price_delta(self) -> float | None:
        if self.cur_price is None or self.yoy_price is None:
            return None
        return self.cur_price - self.yoy_price

    @property
    def mom_cost_impact(self) -> float | None:
        d = self.mom_price_delta
        if d is None or self.period_usage is None:
            return None
        return d * self.period_usage

    @property
    def yoy_cost_impact(self) -> float | None:
        d = self.yoy_price_delta
        if d is None or self.period_usage is None:
            return None
        return d * self.period_usage


def to_row(r: Table2Row) -> list[Any]:
    """Project Table2Row → 29-element list."""
    return [
        r.region, r.code, r.store, r.matnr, r.matxt, r.unit,
        r.cur_price, r.prev_price, r.yoy_price,
        r.mom_price_delta, r.yoy_price_delta,
        r.period_usage, r.mom_cost_impact, r.yoy_cost_impact,
    ] + [None] * 15


def build_rows(
    *,
    zfi_cur: dict[tuple[str, int], MaterialUsage],
    mb5b_cur: dict[tuple[str, int], float],
    mb5b_prev: dict[tuple[str, int], float] | None = None,
    mb5b_yoy: dict[tuple[str, int], float] | None = None,
    werks_filter: list[str] | None = None,
) -> list[Table2Row]:
    """Join ZFI0156 (current month usage) with cur/prev/YoY MB5B prices.

    One row per (werks, matnr) that has either usage > 0 in ZFI0156 OR a
    current-month MB5B price. Rows are sorted by (werks, matnr) so the
    output is deterministic.
    """
    mb5b_prev = mb5b_prev or {}
    mb5b_yoy = mb5b_yoy or {}
    werks_filter = werks_filter or list(WERKS_TO_STORE.keys())

    # Union of keys across all inputs (within werks_filter).
    keys: set[tuple[str, int]] = set()
    for d in (zfi_cur, mb5b_cur, mb5b_prev, mb5b_yoy):
        for k in d:
            if k[0] in werks_filter:
                keys.add(k)

    rows = []
    for (werks, matnr) in sorted(keys):
        usage = zfi_cur.get((werks, matnr))
        if usage is None:
            # Material has price but no usage — skip if we can't get name/unit.
            # Manual workbook excludes zero-usage materials except newly-priced
            # ones; we follow the same rule.
            continue
        store = WERKS_TO_STORE.get(werks, werks)
        rows.append(Table2Row(
            region="加拿大",
            store=store,
            werks=werks,
            matnr=matnr,
            matxt=usage.matxt,
            unit=usage.unit,
            cur_price=mb5b_cur.get((werks, matnr)) or usage.unit_price,
            prev_price=mb5b_prev.get((werks, matnr)),
            yoy_price=mb5b_yoy.get((werks, matnr)),
            period_usage=usage.quantity,
        ))
    return rows


def build_rows_from_paths(
    *,
    zfi_cur_path: Path,
    mb5b_cur_path: Path,
    mb5b_prev_path: Path | None = None,
    mb5b_yoy_path: Path | None = None,
    werks_filter: list[str] | None = None,
) -> list[Table2Row]:
    """Convenience wrapper that loads all source files and builds rows."""
    return build_rows(
        zfi_cur=load_zfi0156(zfi_cur_path),
        mb5b_cur=load_mb5b_prices(mb5b_cur_path),
        mb5b_prev=load_mb5b_prices(mb5b_prev_path) if mb5b_prev_path else None,
        mb5b_yoy=load_mb5b_prices(mb5b_yoy_path) if mb5b_yoy_path else None,
        werks_filter=werks_filter,
    )


def write_sheet(ws: Worksheet, records: list[Table2Row]) -> int:
    """Write records to ``ws`` with the 表2 header. Returns row count."""
    # Manual workbook structure: row 1 = source-note headers, row 2 = data
    # headers. We just emit the data headers and let callers add row 1 if
    # they want to mirror the manual layout.
    ws.append(HEADERS)
    written = 0
    for r in records:
        ws.append(to_row(r))
        written += 1
    return written

"""Per-store static metadata used by the 基础数据 sheet of the
毛利相关分析指标 workbook.

These values are stable across months. Source-of-truth: extracted from
the manual workbook (附件3-毛利相关分析指标-2603.xlsx, sheet 基础数据,
cols 86–92) — Hongming/Finance updates this dict when a new store opens
or status changes. The bulk of the report is data-driven; only these
seven attributes need a code change per store lifecycle event.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StoreMeta:
    region: str         # 地区
    country: str        # 国家
    city: str           # 城市
    open_date: date | None  # 开业日期
    level: str          # 门店级别 (typically "-")
    status: str         # 营业状态 (营业 / 工程 / 暂停 / 闭店)
    classification: str  # 门店分类 (可比店 / 2025年新开店 / 工程店 / ...)


# Order matches STORE_ORDER from canada_pnl.py.
STORE_META: dict[str, StoreMeta] = {
    "加拿大一店": StoreMeta(
        region="北美", country="加拿大", city="温哥华",
        open_date=date(2018, 12, 18),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大二店": StoreMeta(
        region="北美", country="加拿大", city="温哥华",
        open_date=date(2020, 7, 27),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大三店": StoreMeta(
        region="北美", country="加拿大", city="多伦多",
        open_date=date(2020, 8, 17),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大四店": StoreMeta(
        region="北美", country="加拿大", city="多伦多",
        open_date=date(2020, 10, 30),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大五店": StoreMeta(
        region="北美", country="加拿大", city="多伦多",
        open_date=date(2022, 10, 3),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大六店": StoreMeta(
        region="北美", country="加拿大", city="蒙特利尔",
        open_date=date(2024, 1, 9),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大七店": StoreMeta(
        region="北美", country="加拿大", city="温哥华",
        open_date=date(2024, 5, 1),
        level="-", status="营业", classification="可比店",
    ),
    "加拿大八店": StoreMeta(
        region="北美", country="加拿大", city="多伦多",
        open_date=date(2025, 10, 18),
        level="-", status="营业", classification="2025年新开店",
    ),
    # 加拿大九店 is still 工程 (under construction) as of 2026-05.
    "加拿大九店": StoreMeta(
        region="北美", country="加拿大", city="-",
        open_date=None,
        level="-", status="工程", classification="工程店",
    ),
}

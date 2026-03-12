"""Shared builder for comparison sheets (MoM Sheet 1, YoY Sheet 3).

Eliminates ~85% code duplication between mom.py and yoy_detail.py by
parameterizing the comparison period and color theme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from daily_store_operation_report.constants import REGION_LABEL, STORES, WAN_DIVISOR, WEEKDAY_NAMES
from daily_store_operation_report.sheets.styles import (
    BOLD,
    BOLD_LARGE,
    CENTER,
    WHITE_FILL,
    apply_border,
    apply_fill_range,
    apply_fill_row,
)
from daily_store_operation_report.transform import ReportData, StoreMetrics
from daily_store_operation_report.utils import comp_text, div_or_zero, pct_str

_NCOLS = 11  # A..K


@dataclass
class SheetTheme:
    """Color/font theme for a comparison sheet."""

    title_font: Font
    header_font: Font
    header_fill: PatternFill
    section_a_fill: PatternFill  # 桌数 + 单桌消费 sections
    section_b_fill: PatternFill  # 收入 section + turnover alternating
    highlight_fill: PatternFill  # diff/target rows + turnover alternating


@dataclass
class ComparisonConfig:
    """What to compare against (previous month or previous year)."""

    sheet_name: str
    comp_type: str  # "环比" or "同比"
    comp_label: str  # "上月" or "上年"
    get_comp_tables: Callable[[StoreMetrics], float]
    get_comp_raw_tables: Callable[[StoreMetrics], float]
    get_comp_revenue_wan: Callable[[StoreMetrics], float]
    get_comp_per_table: Callable[[StoreMetrics], float]
    theme: SheetTheme


def _write_row(
    ws: Worksheet, row: int, label: str, values: list, *, region_sum: bool = True
) -> None:
    """Write a label + per-store values row, with optional region sum in column K."""
    ws.cell(row=row, column=2, value=label)
    for i, v in enumerate(values):
        ws.cell(row=row, column=3 + i, value=v)
    if region_sum and len(values) == len(STORES):
        ws.cell(
            row=row,
            column=_NCOLS,
            value=sum(v for v in values if isinstance(v, (int, float))),
        )


def build_comparison_sheet(wb: Workbook, data: ReportData, config: ComparisonConfig) -> Worksheet:
    """Build a comparison sheet (MoM or YoY detail)."""
    ws: Worksheet = wb.create_sheet(config.sheet_name)
    dates = data.dates
    d = dates.report_date
    weekday = WEEKDAY_NAMES[d.weekday()]
    month = d.month
    day = d.day
    stores = STORES
    theme = config.theme
    comp = config.comp_label
    comp_type = config.comp_type

    # Row 1: Title
    ws.merge_cells("A1:K1")
    ws["A1"] = f"加拿大-各门店{d.year}年{month:02d}月{day:02d}日{comp_type}数据-{weekday}"
    ws["A1"].font = theme.title_font
    ws["A1"].alignment = CENTER

    # Row 2: Headers
    headers = ["项目", "内容"] + stores + [REGION_LABEL]
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=col_idx, value=h)
        c.font = theme.header_font
        c.alignment = CENTER

    # ── Section 1: 桌数(考核) — rows 3-8 ──
    ws.merge_cells("A3:A8")
    ws["A3"] = "桌数\n(考核)"
    ws["A3"].font = BOLD
    ws["A3"].alignment = CENTER

    _write_row(ws, 3, "今日总桌数", [data.stores[s].today_tables for s in stores])
    _write_row(ws, 4, "今日外卖桌数", [data.stores[s].today_takeout_tables for s in stores])
    _write_row(ws, 5, "今日未计入考核桌数", [data.stores[s].today_non_assessed_tables for s in stores])
    _write_row(ws, 6, f"{month}月总桌数", [data.stores[s].mtd_tables for s in stores])
    _write_row(
        ws, 7, f"{comp}同期总桌数", [config.get_comp_tables(data.stores[s]) for s in stores]
    )

    # Row 8: comparison diff
    diffs = [data.stores[s].mtd_tables - config.get_comp_tables(data.stores[s]) for s in stores]
    _write_row(ws, 8, f"对比{comp}同期总桌数", [comp_text(diff) for diff in diffs], region_sum=False)
    ws.cell(row=8, column=_NCOLS, value=comp_text(sum(diffs)))

    # ── Section 2: 收入(不含税-万加元) — rows 9-17 ──
    ws.merge_cells("A9:A17")
    ws["A9"] = "收入\n(不含税-万加元)"
    ws["A9"].font = BOLD
    ws["A9"].alignment = CENTER

    _write_row(ws, 9, "今日营业收入(万)", [data.stores[s].today_revenue_wan for s in stores])
    _write_row(ws, 10, "本月截止目前营业收入(万)", [data.stores[s].mtd_revenue_wan for s in stores])
    _write_row(
        ws,
        11,
        f"{comp}截止目前营业收入(万)",
        [config.get_comp_revenue_wan(data.stores[s]) for s in stores],
    )
    _write_row(
        ws,
        12,
        f"{comp_type}营业收入变化(万)",
        [data.stores[s].mtd_revenue_wan - config.get_comp_revenue_wan(data.stores[s]) for s in stores],
    )
    _write_row(ws, 13, "本月营业收入目标(万)", [data.stores[s].revenue_target for s in stores])

    # Row 14: target completion %
    vals14 = [
        pct_str(div_or_zero(data.stores[s].mtd_revenue_wan, data.stores[s].revenue_target) * 100)
        for s in stores
    ]
    _write_row(ws, 14, "本月截止目标完成率", vals14, region_sum=False)
    region_mtd = sum(data.stores[s].mtd_revenue_wan for s in stores)
    region_target = sum(data.stores[s].revenue_target for s in stores)
    ws.cell(row=14, column=_NCOLS, value=pct_str(div_or_zero(region_mtd, region_target) * 100))

    # Row 15: standard time progress
    tp = pct_str(dates.time_progress * 100)
    ws.cell(row=15, column=2, value="标准时间进度")
    for col in range(3, _NCOLS + 1):
        ws.cell(row=15, column=col, value=tp)

    # Row 16-17: discounts
    _write_row(ws, 16, "当月累计优惠总金额(万)", [data.stores[s].mtd_discount_wan for s in stores])
    vals17 = [pct_str(data.stores[s].mtd_discount_pct) for s in stores]
    _write_row(ws, 17, "当月累计优惠占比", vals17, region_sum=False)
    region_disc = sum(data.stores[s].mtd_discount_wan for s in stores)
    ws.cell(row=17, column=_NCOLS, value=pct_str(div_or_zero(region_disc, region_mtd) * 100))

    # ── Section 3: 单桌消费(不含税) — rows 18-23 ──
    ws.merge_cells("A18:A23")
    ws["A18"] = "单桌消费\n(不含税)"
    ws["A18"].font = BOLD
    ws["A18"].alignment = CENTER

    # Row 18: per capita
    region_rev_today = sum(data.stores[s].today_revenue_wan * WAN_DIVISOR for s in stores)
    region_cust_today = sum(data.stores[s].today_customers for s in stores)
    _write_row(
        ws, 18, "今日人均消费", [data.stores[s].today_per_capita for s in stores], region_sum=False
    )
    ws.cell(row=18, column=_NCOLS, value=div_or_zero(region_rev_today, region_cust_today))

    # Row 19: customers
    _write_row(ws, 19, "今日消费客数", [data.stores[s].today_customers for s in stores])

    # Row 20: per table today
    region_raw_tables_today = sum(data.stores[s].today_raw_tables for s in stores)
    _write_row(
        ws, 20, "今日单桌消费", [data.stores[s].today_per_table for s in stores], region_sum=False
    )
    ws.cell(row=20, column=_NCOLS, value=div_or_zero(region_rev_today, region_raw_tables_today))

    # Row 21: per table MTD
    region_mtd_raw_rev = sum(data.stores[s].mtd_revenue_wan * WAN_DIVISOR for s in stores)
    region_mtd_raw_tables = sum(data.stores[s].mtd_raw_tables for s in stores)
    _write_row(
        ws, 21, "截止今日单桌消费", [data.stores[s].mtd_per_table for s in stores], region_sum=False
    )
    ws.cell(row=21, column=_NCOLS, value=div_or_zero(region_mtd_raw_rev, region_mtd_raw_tables))

    # Row 22: comparison period per table
    region_comp_rev = sum(
        config.get_comp_revenue_wan(data.stores[s]) * WAN_DIVISOR for s in stores
    )
    region_comp_raw_tables = sum(config.get_comp_raw_tables(data.stores[s]) for s in stores)
    _write_row(
        ws,
        22,
        f"{comp}单桌消费",
        [config.get_comp_per_table(data.stores[s]) for s in stores],
        region_sum=False,
    )
    ws.cell(row=22, column=_NCOLS, value=div_or_zero(region_comp_rev, region_comp_raw_tables))

    # Row 23: per table change
    _write_row(
        ws,
        23,
        f"{comp_type}{comp}变化",
        [data.stores[s].mtd_per_table - config.get_comp_per_table(data.stores[s]) for s in stores],
        region_sum=False,
    )
    ws.cell(
        row=23,
        column=_NCOLS,
        value=(
            div_or_zero(region_mtd_raw_rev, region_mtd_raw_tables)
            - div_or_zero(region_comp_rev, region_comp_raw_tables)
        ),
    )

    # ── Section 4: 翻台率 — rows 24-28 ──
    ws.merge_cells("A24:A28")
    ws["A24"] = "翻台率"
    ws["A24"].font = BOLD
    ws["A24"].alignment = CENTER

    ws.cell(row=24, column=2, value="名次")
    for i in range(len(stores)):
        ws.cell(row=24, column=3 + i, value=f"第{i + 1}名")
    ws.cell(row=24, column=_NCOLS, value="当月累计平均翻台率")

    # Today ranking
    today_tr = [(s, data.stores[s].today_turnover_rate) for s in stores]
    today_tr.sort(key=lambda x: x[1], reverse=True)
    ws.cell(row=25, column=2, value=f"{month}月{day}日翻台率排名店铺")
    ws.cell(row=26, column=2, value=f"{month}月{day}日翻台率排名")
    for i, (store, tr) in enumerate(today_tr):
        ws.cell(row=25, column=3 + i, value=store)
        ws.cell(row=26, column=3 + i, value=tr)

    # K25:K28 merged — region average turnover rate (exclude stores with no data)
    ws.merge_cells("K25:K28")
    nonzero_rates = [data.stores[s].mtd_turnover_rate for s in stores if data.stores[s].mtd_tables > 0]
    region_avg_tr = sum(nonzero_rates) / len(nonzero_rates) if nonzero_rates else 0
    ws["K25"] = region_avg_tr
    ws["K25"].font = BOLD_LARGE
    ws["K25"].alignment = CENTER

    # MTD ranking
    mtd_tr = [(s, data.stores[s].mtd_turnover_rate) for s in stores]
    mtd_tr.sort(key=lambda x: x[1], reverse=True)
    ws.cell(row=27, column=2, value=f"{month}月平均翻台率排名店铺")
    ws.cell(row=28, column=2, value=f"{month}月平均翻台率排名")
    for i, (store, tr) in enumerate(mtd_tr):
        ws.cell(row=27, column=3 + i, value=store)
        ws.cell(row=28, column=3 + i, value=tr)

    # ── Styling ──
    apply_fill_row(ws, 1, theme.header_fill, 1, _NCOLS)
    apply_fill_row(ws, 2, theme.header_fill, 1, _NCOLS)

    apply_fill_range(ws, 3, 7, theme.section_a_fill, 1, _NCOLS)
    apply_fill_range(ws, 18, 22, theme.section_a_fill, 1, _NCOLS)

    apply_fill_row(ws, 8, theme.highlight_fill, 1, _NCOLS)
    apply_fill_row(ws, 14, theme.highlight_fill, 1, _NCOLS)

    apply_fill_range(ws, 9, 13, theme.section_b_fill, 1, _NCOLS)
    apply_fill_range(ws, 15, 17, theme.section_b_fill, 1, _NCOLS)

    apply_fill_row(ws, 23, theme.section_a_fill, 1, _NCOLS)

    # Turnover section: alternating highlight / section_b
    apply_fill_row(ws, 24, theme.highlight_fill, 1, _NCOLS)
    apply_fill_row(ws, 25, theme.section_b_fill, 1, _NCOLS)
    apply_fill_row(ws, 26, theme.highlight_fill, 1, _NCOLS)
    apply_fill_row(ws, 27, theme.section_b_fill, 1, _NCOLS)
    apply_fill_row(ws, 28, theme.highlight_fill, 1, _NCOLS)

    # K25 white fill override (after row styling)
    ws["K25"].fill = WHITE_FILL

    # Borders
    apply_border(ws, 1, 28, 1, _NCOLS)

    # Alignment
    for row in ws.iter_rows(min_row=2, max_row=28, min_col=1, max_col=_NCOLS):
        for cell in row:
            cell.alignment = CENTER

    # Column widths
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 28
    for col in range(3, _NCOLS + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    return ws

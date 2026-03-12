"""Sheet 1: 对比上月表 (Month-over-Month comparison, gold theme)."""

from __future__ import annotations

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from daily_store_operation_report.sheets.comparison_sheet import (
    ComparisonConfig,
    SheetTheme,
    build_comparison_sheet,
)
from daily_store_operation_report.sheets.styles import (
    BOLD,
    BOLD_TITLE,
    BRIGHT_YELLOW_FILL,
    GOLD_FILL,
    LIGHT_BLUE_FILL_GOLD,
    YELLOW_FILL,
)
from daily_store_operation_report.transform import ReportData

_GOLD_THEME = SheetTheme(
    title_font=BOLD_TITLE,
    header_font=BOLD,
    header_fill=GOLD_FILL,
    section_a_fill=YELLOW_FILL,
    section_b_fill=LIGHT_BLUE_FILL_GOLD,
    highlight_fill=BRIGHT_YELLOW_FILL,
)

_MOM_CONFIG = ComparisonConfig(
    sheet_name="对比上月表",
    comp_type="环比",
    comp_label="上月",
    get_comp_tables=lambda m: m.prev_mtd_tables,
    get_comp_raw_tables=lambda m: m.prev_mtd_raw_tables,
    get_comp_revenue_wan=lambda m: m.prev_mtd_revenue_wan,
    get_comp_per_table=lambda m: m.prev_mtd_per_table,
    theme=_GOLD_THEME,
)


def build_mom_sheet(wb: Workbook, data: ReportData) -> Worksheet:
    """Build the 对比上月表 sheet."""
    return build_comparison_sheet(wb, data, _MOM_CONFIG)

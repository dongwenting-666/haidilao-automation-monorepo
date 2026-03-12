"""Sheet 3: 对比上年表 (Year-over-Year detail, blue theme)."""

from __future__ import annotations

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from daily_store_operation_report.sheets.comparison_sheet import (
    ComparisonConfig,
    SheetTheme,
    build_comparison_sheet,
)
from daily_store_operation_report.sheets.styles import (
    DARK_BLUE_FILL,
    LIGHT_BLUE_FILL,
    MED_BLUE_FILL,
    PALE_BLUE_FILL,
    WHITE_BOLD,
    WHITE_BOLD_TITLE,
)
from daily_store_operation_report.transform import ReportData

_BLUE_THEME = SheetTheme(
    title_font=WHITE_BOLD_TITLE,
    header_font=WHITE_BOLD,
    header_fill=DARK_BLUE_FILL,
    section_a_fill=PALE_BLUE_FILL,
    section_b_fill=LIGHT_BLUE_FILL,
    highlight_fill=MED_BLUE_FILL,
)

_YOY_CONFIG = ComparisonConfig(
    sheet_name="对比上年表",
    comp_type="同比",
    comp_label="上年",
    get_comp_tables=lambda m: m.yoy_mtd_tables,
    get_comp_raw_tables=lambda m: m.yoy_mtd_raw_tables,
    get_comp_revenue_wan=lambda m: m.yoy_mtd_revenue_wan,
    get_comp_per_table=lambda m: m.yoy_mtd_per_table,
    theme=_BLUE_THEME,
)


def build_yoy_detail_sheet(wb: Workbook, data: ReportData) -> Worksheet:
    """Build the 对比上年表 sheet."""
    return build_comparison_sheet(wb, data, _YOY_CONFIG)

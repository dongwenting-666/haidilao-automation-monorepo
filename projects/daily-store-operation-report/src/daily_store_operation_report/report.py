"""Report orchestrator — builds all sheets and saves the workbook."""

from __future__ import annotations

from pathlib import Path

from excel_utils import create_workbook
from openpyxl.workbook import Workbook

from daily_store_operation_report.sheets.competitor import (
    build_competitor_sheet,
    build_competitor_takeout_sheet,
)
from daily_store_operation_report.sheets.mom import build_mom_sheet
from daily_store_operation_report.sheets.time_period import build_time_period_sheet
from daily_store_operation_report.sheets.yoy_detail import build_yoy_detail_sheet
from daily_store_operation_report.sheets.yoy_summary import build_yoy_summary_sheet
from daily_store_operation_report.transform import ReportData


def _format_numbers(wb: Workbook) -> None:
    """Apply '0.00' display format to all float cells.

    Cells retain full precision internally; only the Excel display
    format is set to 2 decimal places.  Integer cells (e.g. customer
    counts) are left as-is so they display without decimal places.
    """
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = "0.00"


def generate_report(data: ReportData, output_dir: Path) -> Path:
    """Generate the full Excel report and save it."""
    wb = create_workbook()

    build_mom_sheet(wb, data)
    build_yoy_summary_sheet(wb, data)
    build_yoy_detail_sheet(wb, data)
    build_time_period_sheet(wb, data)
    build_competitor_sheet(wb, data)
    build_competitor_takeout_sheet(wb, data)
    _format_numbers(wb)

    output_dir.mkdir(parents=True, exist_ok=True)
    d = data.dates.report_date
    filename = f"database_report_{d.year}_{d.month:02d}_{d.day:02d}.xlsx"
    output_path = output_dir / filename
    try:
        wb.save(output_path)
    except PermissionError:
        raise PermissionError(
            f"Cannot save {output_path} — is the file open in Excel?"
        ) from None
    return output_path

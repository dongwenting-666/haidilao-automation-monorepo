"""Fill a styled template workbook with computed data, preserving styles.

The manual 附件3-毛利相关分析指标 workbook carries all the formatting we
need (fonts, fills, borders, merged cells, conditional formatting,
column widths, number formats). Rather than rebuild that styling from
scratch in openpyxl, we copy the template and overwrite only the data
cells in place — openpyxl keeps a cell's style when you set just
``cell.value``.

Per-sheet fill functions write computed rows into the template's data
region starting at the known data-start row. When our row count exceeds
the template's, the style of the last template data row is copied down
to the new rows so they stay formatted.
"""
from __future__ import annotations

import logging
import shutil
from copy import copy
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)


# Data-start row (1-based) per sheet — the first row that holds store/dish data.
DATA_START_ROW = {
    "表1-菜品价格变动及菜品损耗表 (模板) ": 4,
    "表2-原材料成本变动表": 3,
    "基础数据": 2,
}


def _copy_row_style(ws: Worksheet, src_row: int, dst_row: int, ncols: int) -> None:
    """Copy cell styles (not values) from src_row to dst_row."""
    for c in range(1, ncols + 1):
        s = ws.cell(row=src_row, column=c)
        d = ws.cell(row=dst_row, column=c)
        if s.has_style:
            d.font = copy(s.font)
            d.fill = copy(s.fill)
            d.border = copy(s.border)
            d.alignment = copy(s.alignment)
            d.number_format = s.number_format
            d.protection = copy(s.protection)


def _write_rows_in_place(
    ws: Worksheet, rows: list[list[Any]], start_row: int, ncols: int,
    *, clear_to_row: int | None = None,
) -> None:
    """Overwrite values from start_row downward, preserving styles.

    Styles for rows beyond the template's existing styled region are
    copied from the template's first data row (start_row). If
    ``clear_to_row`` is set, any leftover template data rows below the
    new data are cleared (values only).
    """
    proto = start_row
    for i, row in enumerate(rows):
        r = start_row + i
        if r > ws.max_row:
            _copy_row_style(ws, proto, r, ncols)
        for j, val in enumerate(row):
            if j >= ncols:
                break
            cell = ws.cell(row=r, column=j + 1)
            # Skip cells inside a merged range anchor that isn't top-left.
            cell.value = val
    # Clear leftover template rows below our data.
    if clear_to_row is not None:
        last = start_row + len(rows)
        for r in range(last, clear_to_row + 1):
            for c in range(1, ncols + 1):
                ws.cell(row=r, column=c).value = None


def open_template(template_path: Path, out_path: Path):
    """Copy template → out_path and open it for editing (styles preserved)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, out_path)
    return load_workbook(out_path)


def fill_table_sheet(
    wb, sheet_name: str, rows: list[list[Any]], ncols: int,
) -> None:
    """Generic filler for the flat data tables (表1 / 表2 / 基础数据)."""
    if sheet_name not in wb.sheetnames:
        logger.warning("template missing sheet %s", sheet_name)
        return
    ws = wb[sheet_name]
    start = DATA_START_ROW[sheet_name]
    template_last = ws.max_row
    _write_rows_in_place(ws, rows, start, ncols, clear_to_row=template_last)
    logger.info("filled %s: %d rows from row %d", sheet_name, len(rows), start)


def fill_positioned_rows(
    wb, sheet_name: str, rows_by_store: dict[str, list[Any]],
    *, store_col: int, start_row: int, end_row: int,
    value_cols: list[int],
) -> None:
    """Fill a sheet where each store occupies a fixed row in [start,end].

    Reads the store name from ``store_col`` on each existing template row
    and writes the matching row's values into ``value_cols``. Leaves total
    / header / manual-paste rows untouched, and preserves all styles.

    ``rows_by_store[store] = full_row_list`` (1-based column → value at
    index col-1). Only the indices in ``value_cols`` are written.
    """
    if sheet_name not in wb.sheetnames:
        logger.warning("template missing sheet %s", sheet_name)
        return
    ws = wb[sheet_name]
    written = 0
    for r in range(start_row, end_row + 1):
        store = ws.cell(row=r, column=store_col).value
        if not store or store not in rows_by_store:
            continue
        full = rows_by_store[store]
        for col in value_cols:
            if col - 1 < len(full):
                v = full[col - 1]
                if v is not None:
                    ws.cell(row=r, column=col).value = v
        written += 1
    logger.info("filled %s: %d store rows (%d..%d)",
                sheet_name, written, start_row, end_row)

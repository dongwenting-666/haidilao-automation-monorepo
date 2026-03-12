"""Shared Excel generation utilities for Haidilao automations."""

from importlib.metadata import version

from excel_utils.reader import load_data_rows, load_mapping
from excel_utils.style import BOLD_FONT, auto_size_columns, set_header_row
from excel_utils.workbook import (
    MAX_SHEET_NAME_LEN,
    copy_sheet_data,
    create_workbook,
    truncate_sheet_name,
    write_data_sheet,
)

__version__ = version("excel-utils")

__all__ = [
    "BOLD_FONT",
    "MAX_SHEET_NAME_LEN",
    "auto_size_columns",
    "copy_sheet_data",
    "create_workbook",
    "load_data_rows",
    "load_mapping",
    "set_header_row",
    "truncate_sheet_name",
    "write_data_sheet",
]

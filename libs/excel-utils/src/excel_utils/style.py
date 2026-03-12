"""Excel styling utilities."""

from __future__ import annotations

from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

BOLD_FONT = Font(bold=True)

_DEFAULT_MAX_WIDTH = 40
_DEFAULT_MIN_WIDTH = 10
_WIDTH_PADDING = 4


def set_header_row(
    ws: Worksheet,
    headers: list[str],
    *,
    row: int = 1,
    font: Font = BOLD_FONT,
) -> None:
    """Write a bold header row.

    Args:
        ws: Target worksheet.
        headers: List of header labels.
        row: Row number to write at (1-based).
        font: Font style for header cells.
    """
    for col, header in enumerate(headers, 1):
        ws.cell(row=row, column=col, value=header).font = font


def auto_size_columns(
    ws: Worksheet,
    *,
    max_width: int = _DEFAULT_MAX_WIDTH,
    min_width: int = _DEFAULT_MIN_WIDTH,
) -> None:
    """Auto-size columns based on content width.

    Args:
        ws: Target worksheet.
        max_width: Maximum column width.
        min_width: Minimum column width.
    """
    for col in ws.columns:
        max_len = max(
            (len(str(cell.value or "")) for cell in col),
            default=min_width,
        )
        width = min(max_len + _WIDTH_PADDING, max_width)
        width = max(width, min_width)
        ws.column_dimensions[col[0].column_letter].width = width

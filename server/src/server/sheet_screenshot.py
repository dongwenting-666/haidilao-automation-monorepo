"""Render Excel worksheet tabs as PNG images for Lark delivery.

Uses openpyxl to read cell values and Pillow to draw a table-style image.
Handles merged cells, number formatting, and auto-sizing columns.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from openpyxl.worksheet.worksheet import Worksheet

log = logging.getLogger(__name__)

# ── Layout constants ──────────────────────────────────────────────────────────
_CELL_PAD_X = 12       # horizontal padding inside each cell
_CELL_PAD_Y = 8        # vertical padding inside each cell
_ROW_HEIGHT = 32       # fixed row height in pixels
_HEADER_BG = (59, 130, 246)    # blue header background
_HEADER_FG = (255, 255, 255)   # white header text
_ALT_ROW_BG = (241, 245, 249)  # light grey-blue for alternating rows
_GRID_COLOR = (209, 213, 219)  # border/grid line color
_TEXT_COLOR = (31, 41, 55)     # dark text
_TITLE_BG = (30, 58, 138)     # dark blue for sheet title bar
_TITLE_FG = (255, 255, 255)
_TITLE_HEIGHT = 44
_MAX_COL_WIDTH = 320   # cap column width to prevent ultra-wide images
_MIN_COL_WIDTH = 70


def _try_load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a CJK-capable font, falling back to the default bitmap font."""
    # macOS system fonts that handle CJK
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _cell_display_value(cell) -> str:
    """Get the display string for a cell, respecting number formats."""
    if cell.value is None:
        return ""
    v = cell.value
    fmt = cell.number_format or "General"

    if isinstance(v, float):
        if "%" in fmt:
            return f"{v * 100:.2f}%"
        if "0.00" in fmt:
            return f"{v:,.2f}"
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _get_merged_value(ws: "Worksheet", row: int, col: int) -> str | None:
    """If (row, col) is inside a merged range, return the top-left cell value."""
    for merge_range in ws.merged_cells.ranges:
        if (row, col) in [(r, c) for r in range(merge_range.min_row, merge_range.max_row + 1)
                          for c in range(merge_range.min_col, merge_range.max_col + 1)]:
            cell = ws.cell(merge_range.min_row, merge_range.min_col)
            return _cell_display_value(cell)
    return None


def render_sheet(ws: "Worksheet", sheet_name: str) -> bytes:
    """Render a single worksheet to a PNG image (returned as bytes).

    The image looks like a clean data table with a title bar showing the
    sheet name, a coloured header row, alternating row backgrounds, and
    grid lines.
    """
    font = _try_load_font(14)
    font_bold = _try_load_font(15)
    font_title = _try_load_font(18)

    max_row = ws.max_row or 1
    max_col = ws.max_column or 1

    # Read all cell text values
    grid: list[list[str]] = []
    for r in range(1, max_row + 1):
        row_vals: list[str] = []
        for c in range(1, max_col + 1):
            cell = ws.cell(r, c)
            text = _cell_display_value(cell)
            if not text:
                # Check if part of a merged range
                merged = _get_merged_value(ws, r, c)
                if merged:
                    text = merged
            row_vals.append(text)
        grid.append(row_vals)

    if not grid:
        return b""

    # Compute column widths based on content
    col_widths: list[int] = []
    for c in range(max_col):
        max_w = _MIN_COL_WIDTH
        for row_vals in grid:
            if c < len(row_vals):
                try:
                    bbox = font.getbbox(row_vals[c])
                    w = bbox[2] - bbox[0] if bbox else 0
                except Exception:
                    w = len(row_vals[c]) * 9
                max_w = max(max_w, w + _CELL_PAD_X * 2)
        col_widths.append(min(max_w, _MAX_COL_WIDTH))

    # Image dimensions
    table_width = sum(col_widths) + 1  # +1 for right border
    table_height = _TITLE_HEIGHT + _ROW_HEIGHT * max_row + 1
    img_width = table_width + 20   # 10px margin each side
    img_height = table_height + 20

    img = Image.new("RGB", (img_width, img_height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    x_offset = 10
    y_offset = 10

    # Title bar
    draw.rectangle(
        [x_offset, y_offset, x_offset + table_width - 1, y_offset + _TITLE_HEIGHT - 1],
        fill=_TITLE_BG,
    )
    draw.text(
        (x_offset + 16, y_offset + (_TITLE_HEIGHT - 18) // 2),
        sheet_name,
        fill=_TITLE_FG,
        font=font_title,
    )

    # Draw rows
    y = y_offset + _TITLE_HEIGHT
    for row_idx, row_vals in enumerate(grid):
        x = x_offset
        is_header = row_idx == 0
        is_alt = not is_header and row_idx % 2 == 0

        # Row background
        if is_header:
            bg = _HEADER_BG
        elif is_alt:
            bg = _ALT_ROW_BG
        else:
            bg = (255, 255, 255)

        draw.rectangle(
            [x, y, x + table_width - 1, y + _ROW_HEIGHT - 1],
            fill=bg,
        )

        # Cell values
        for col_idx, text in enumerate(row_vals):
            if col_idx >= len(col_widths):
                break
            cw = col_widths[col_idx]

            # Truncate if too long
            display = text
            try:
                bbox = font.getbbox(display)
                tw = bbox[2] - bbox[0] if bbox else 0
            except Exception:
                tw = len(display) * 9
            while tw > cw - _CELL_PAD_X * 2 and len(display) > 1:
                display = display[:-2] + "…"
                try:
                    bbox = font.getbbox(display)
                    tw = bbox[2] - bbox[0] if bbox else 0
                except Exception:
                    tw = len(display) * 9

            fg = _HEADER_FG if is_header else _TEXT_COLOR
            f = font_bold if is_header else font

            # Right-align numbers, left-align text
            is_numeric = text and any(ch.isdigit() for ch in text) and not any(
                u'\u4e00' <= ch <= u'\u9fff' for ch in text
            )
            if is_numeric and not is_header:
                text_x = x + cw - _CELL_PAD_X - tw
            else:
                text_x = x + _CELL_PAD_X

            text_y = y + (_ROW_HEIGHT - 14) // 2
            draw.text((text_x, text_y), display, fill=fg, font=f)

            # Vertical grid line
            draw.line([(x + cw, y), (x + cw, y + _ROW_HEIGHT)], fill=_GRID_COLOR)

            x += cw

        # Horizontal grid line
        draw.line([(x_offset, y + _ROW_HEIGHT), (x_offset + table_width - 1, y + _ROW_HEIGHT)], fill=_GRID_COLOR)

        y += _ROW_HEIGHT

    # Outer border
    draw.rectangle(
        [x_offset, y_offset + _TITLE_HEIGHT, x_offset + table_width - 1, y],
        outline=_GRID_COLOR,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_all_sheets(xlsx_path: Path) -> list[tuple[str, bytes]]:
    """Render every sheet in an xlsx file to PNG images.

    Returns a list of (sheet_name, png_bytes) tuples.
    """
    wb = load_workbook(xlsx_path, data_only=True)
    results: list[tuple[str, bytes]] = []

    for name in wb.sheetnames:
        ws = wb[name]
        try:
            png = render_sheet(ws, name)
            if png:
                results.append((name, png))
                log.info("Rendered sheet '%s' as PNG (%d bytes)", name, len(png))
        except Exception:
            log.exception("Failed to render sheet '%s'", name)

    return results

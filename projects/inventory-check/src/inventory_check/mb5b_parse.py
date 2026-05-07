"""Parse MB5B's "Spreadsheet" export (UTF-16 LE tab-separated text).

SAP's MB5B `System -> List -> Save -> Local File -> Spreadsheet` does not
write a real .xlsx — it writes a UTF-16 LE TSV file (with .xls extension
by convention). The header row holds the localized SAP column names.

We expose a column-name-keyed iterator so downstream code doesn't depend
on byte ordering, encoding, or column index quirks.

Real schema (CA08 202603, observed in the manual workbook's
``本月系统单价mb5b`` sheet — 18 columns)::

    ValA   物料   开始日期   结束日期
    期初库存   总收货数量   总发货数量   期末库存
    计   期初金额   总收货金额   总发货金额   期末金额
    货币   物料描述   单价   单位   <unnamed numeric>

Whitespace in headers is collapsed because SAP right-aligns numeric
column titles by padding with spaces.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Header alias map → canonical key. Any header whose collapsed (whitespace
# stripped + lowercased) form matches a key here is renamed.
_HEADER_ALIASES: dict[str, str] = {
    "vala": "Werks",                 # plant code (CA08, CA09, …)
    "工厂": "Werks",
    "物料": "Matnr",
    "物料描述": "Matxt",
    "开始日期": "DateFrom",
    "结束日期": "DateTo",
    "期初库存": "OpeningQty",
    "总收货数量": "ReceiptsQty",
    "总发货数量": "IssuesQty",
    "期末库存": "ClosingQty",
    "计": "MeinsAlt",                # secondary unit
    "期初金额": "OpeningAmt",
    "总收货金额": "ReceiptsAmt",
    "总发货金额": "IssuesAmt",
    "期末金额": "ClosingAmt",
    "货币": "Currency",
    "单价": "UnitPrice",
    "单位": "Meins",
}


_WHITESPACE = re.compile(r"\s+")


def _normalize_header(h: str) -> str:
    return _WHITESPACE.sub("", h.strip()).lower()


def canonicalize_header(h: str) -> str:
    """Map a raw SAP header to a canonical key (or pass through the original)."""
    norm = _normalize_header(h)
    return _HEADER_ALIASES.get(norm, h.strip())


def _coerce_value(v: str) -> Any:
    """Best-effort coercion: numbers → float, blanks → '', else string."""
    s = v.strip()
    if s == "":
        return ""
    try:
        f = float(s.replace(",", ""))
    except ValueError:
        return s
    return int(f) if f.is_integer() else f


def read_mb5b_text(path: str | Path) -> str:
    """Read an MB5B Spreadsheet export and return decoded text.

    SAP writes UTF-16 LE with a BOM. We accept that, plain UTF-16, or
    UTF-8 as fallbacks (a few sites configure GUI to write UTF-8 TSV).
    """
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le")[1:]  # strip BOM
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be")[1:]
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    # Heuristic: if every other byte looks ASCII NUL, assume UTF-16 LE no-BOM.
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode("utf-16-le")
    return raw.decode("utf-8", errors="replace")


def parse_mb5b_text(text: str) -> list[dict[str, Any]]:
    """Parse decoded MB5B TSV text into row dicts keyed by canonical headers."""
    # SAP writes \r\n line breaks; some platforms strip \r so be lenient.
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return []

    headers_raw = lines[0].split("\t")
    headers = [canonicalize_header(h) for h in headers_raw]
    rows: list[dict[str, Any]] = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        # Right-pad in case SAP truncated trailing empty cells.
        while len(cells) < len(headers):
            cells.append("")
        row = {headers[i]: _coerce_value(cells[i]) for i in range(len(headers))}
        rows.append(row)
    logger.info("parsed %d MB5B rows (%d columns)", len(rows), len(headers))
    return rows


def parse_mb5b_file(path: str | Path) -> list[dict[str, Any]]:
    """Top-level: read file, decode, parse — returns row dicts."""
    return parse_mb5b_text(read_mb5b_text(path))


def filter_by_werks(
    rows: list[dict[str, Any]], werks: str
) -> Iterator[dict[str, Any]]:
    """Yield only rows for one plant (e.g. ``"CA08"``)."""
    for r in rows:
        if r.get("Werks") == werks:
            yield r

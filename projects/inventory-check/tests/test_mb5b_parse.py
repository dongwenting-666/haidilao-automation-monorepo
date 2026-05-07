"""Unit tests for inventory_check.mb5b_parse."""
from __future__ import annotations

from pathlib import Path

import pytest

from inventory_check.mb5b_parse import (
    canonicalize_header,
    filter_by_werks,
    parse_mb5b_file,
    parse_mb5b_text,
    read_mb5b_text,
)


# ── header canonicalization ────────────────────────────────────────────


def test_canonicalize_known_chinese_headers() -> None:
    assert canonicalize_header("物料") == "Matnr"
    assert canonicalize_header("期初库存") == "OpeningQty"
    assert canonicalize_header("期末库存") == "ClosingQty"


def test_canonicalize_strips_whitespace() -> None:
    """SAP right-pads numeric column titles with spaces."""
    assert canonicalize_header("                   期初库存") == "OpeningQty"
    assert canonicalize_header("  期末库存  ") == "ClosingQty"


def test_canonicalize_vala_to_werks() -> None:
    assert canonicalize_header("ValA") == "Werks"
    assert canonicalize_header("vala") == "Werks"


def test_canonicalize_unknown_passes_through() -> None:
    assert canonicalize_header("MysteryColumn") == "MysteryColumn"
    assert canonicalize_header("  trim me  ") == "trim me"


# ── parse_mb5b_text ────────────────────────────────────────────────────


_HEADER_LINE = "\t".join([
    "ValA", "物料", "开始日期", "结束日期",
    "                   期初库存",
    "                  总收货数量",
    "                  总发货数量",
    "                   期末库存",
    "计",
    "                   期初金额",
    "                  总收货金额",
    "                  总发货金额",
    "                   期末金额",
    "货币", "物料描述", "单价", "单位", "20",
])

_DATA_LINE_1 = "\t".join([
    "CA08", "1000049", "2026.03.01", "2026.03.31",
    "63.7", "127.4", "-9.8", "181.3",
    "L",
    "149.5", "431", "-29.77", "550.73",
    "CAD", "金标生抽", "3.0376", "公升", "1",
])

_DATA_LINE_2 = "\t".join([
    "CA08", "1000052", "2026.03.01", "2026.03.31",
    "0", "0", "0", "0",
    "KG",
    "0", "0", "0", "0",
    "CAD", "韩式辣椒酱", "0", "公斤", "1",
])

_DATA_LINE_3 = "\t".join([
    "CA09", "1000049", "2026.03.01", "2026.03.31",
    "10", "5", "-2", "13",
    "L",
    "0", "0", "0", "0",
    "CAD", "金标生抽 CA09", "0", "公升", "1",
])

_SAMPLE = "\r\n".join([_HEADER_LINE, _DATA_LINE_1, _DATA_LINE_2, _DATA_LINE_3, ""])


def test_parse_mb5b_text_row_count() -> None:
    rows = parse_mb5b_text(_SAMPLE)
    assert len(rows) == 3


def test_parse_mb5b_text_row_keys_canonicalized() -> None:
    rows = parse_mb5b_text(_SAMPLE)
    keys = set(rows[0].keys())
    # Canonical names from the alias map are present:
    assert {"Werks", "Matnr", "DateFrom", "DateTo", "OpeningQty",
            "ReceiptsQty", "IssuesQty", "ClosingQty", "Currency",
            "UnitPrice", "Meins", "Matxt"}.issubset(keys)


def test_parse_mb5b_text_numeric_coercion() -> None:
    rows = parse_mb5b_text(_SAMPLE)
    r = rows[0]
    assert r["OpeningQty"] == pytest.approx(63.7)
    assert r["ReceiptsQty"] == pytest.approx(127.4)
    assert r["IssuesQty"] == pytest.approx(-9.8)
    assert r["ClosingQty"] == pytest.approx(181.3)
    # Integer-like floats become int (so xlsx renders without trailing .0).
    assert r["ReceiptsAmt"] == 431 and isinstance(r["ReceiptsAmt"], int)


def test_parse_mb5b_text_strings_preserved() -> None:
    rows = parse_mb5b_text(_SAMPLE)
    assert rows[0]["Werks"] == "CA08"
    assert rows[0]["Matnr"] == 1000049  # numeric — coerced
    assert rows[0]["Currency"] == "CAD"
    assert rows[0]["Meins"] == "公升"


def test_parse_mb5b_text_handles_lf_only() -> None:
    text = _SAMPLE.replace("\r\n", "\n")
    rows = parse_mb5b_text(text)
    assert len(rows) == 3


def test_parse_mb5b_text_blank_input() -> None:
    assert parse_mb5b_text("") == []
    assert parse_mb5b_text("\r\n\r\n") == []


def test_parse_mb5b_text_pads_short_rows() -> None:
    """SAP can omit trailing empty cells. Parser must still produce the
    full key set for that row."""
    short_data = "\t".join(["CA08", "1000049"])  # only 2 cells
    text = "\r\n".join([_HEADER_LINE, short_data])
    rows = parse_mb5b_text(text)
    assert len(rows) == 1
    # All header columns are present, missing ones become "".
    assert rows[0]["ClosingQty"] == ""
    assert rows[0]["Currency"] == ""


# ── filter_by_werks ────────────────────────────────────────────────────


def test_filter_by_werks() -> None:
    rows = parse_mb5b_text(_SAMPLE)
    ca08 = list(filter_by_werks(rows, "CA08"))
    ca09 = list(filter_by_werks(rows, "CA09"))
    nope = list(filter_by_werks(rows, "ZZ99"))
    assert len(ca08) == 2
    assert len(ca09) == 1
    assert len(nope) == 0


# ── read_mb5b_text (encoding handling) ─────────────────────────────────


def test_read_mb5b_text_utf16_le_with_bom(tmp_path: Path) -> None:
    p = tmp_path / "mb5b.xls"
    p.write_bytes(b"\xff\xfe" + _SAMPLE.encode("utf-16-le"))
    text = read_mb5b_text(p)
    rows = parse_mb5b_text(text)
    assert len(rows) == 3


def test_read_mb5b_text_utf16_le_no_bom(tmp_path: Path) -> None:
    p = tmp_path / "mb5b.xls"
    p.write_bytes(_SAMPLE.encode("utf-16-le"))
    text = read_mb5b_text(p)
    rows = parse_mb5b_text(text)
    assert len(rows) == 3


def test_read_mb5b_text_utf8_bom(tmp_path: Path) -> None:
    p = tmp_path / "mb5b.xls"
    p.write_bytes(b"\xef\xbb\xbf" + _SAMPLE.encode("utf-8"))
    text = read_mb5b_text(p)
    rows = parse_mb5b_text(text)
    assert len(rows) == 3


def test_read_mb5b_text_plain_utf8_fallback(tmp_path: Path) -> None:
    """No BOM, ASCII-mostly content → falls back to UTF-8."""
    p = tmp_path / "mb5b.xls"
    p.write_bytes(_SAMPLE.encode("utf-8"))
    text = read_mb5b_text(p)
    rows = parse_mb5b_text(text)
    assert len(rows) == 3


# ── parse_mb5b_file (round-trip) ───────────────────────────────────────


def test_parse_mb5b_file_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "mb5b.xls"
    p.write_bytes(b"\xff\xfe" + _SAMPLE.encode("utf-16-le"))
    rows = parse_mb5b_file(p)
    assert len(rows) == 3
    assert rows[0]["ClosingQty"] == pytest.approx(181.3)

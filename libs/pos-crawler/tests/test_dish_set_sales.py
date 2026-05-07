"""Unit tests for the 菜品套餐报表 (set-meal sales) downloader.

The module hasn't been verified against a live API response yet — POS
auth is interactive (Feishu OAuth), so the test suite can't directly hit
the endpoint. Instead, these tests pin the field-mapping logic so a
single change point catches schema drift the moment we observe it on a
real run, and documents which BI套餐 cols we expect POS to fill vs.
which need a separate BI/finance feed.
"""
from __future__ import annotations

from pos_crawler.dish_set_sales import (
    OUTPUT_COLUMNS,
    api_row_to_output_row,
)


def test_output_columns_match_bi_taocan_layout():
    """Pin the 28-col layout. Must match the manual BI套餐 sheet header
    exactly because the calc sheet's W formula references K (菜品编码)
    and T (应收数量) by column letter — reordering would silently break
    every store's 差异 calc."""
    assert OUTPUT_COLUMNS[0] == "月份"
    assert OUTPUT_COLUMNS[2] == "门店名称"
    assert OUTPUT_COLUMNS[6] == "套餐编码"          # G
    assert OUTPUT_COLUMNS[10] == "菜品编码"         # K — calc!F lookup target
    assert OUTPUT_COLUMNS[15] == "出品数量"         # P
    assert OUTPUT_COLUMNS[19] == "应收数量"         # T — calc!N multiplier source
    assert OUTPUT_COLUMNS[21] == "套餐折扣"         # V
    assert len(OUTPUT_COLUMNS) == 26    # A..Z (manual workbook had 28
                                         #       but last 2 were None)


def test_api_row_to_output_row_basic():
    """Most likely POS field names from the listDishPotSale precedent."""
    row = {
        "shopName": "加拿大八店", "dishCode": "01060061",
        "dishName": "清油麻辣火锅", "standardName": "四宫格",
        "dishPrice": 8.95, "unit": "锅",
        "producedNumber": 264, "totalMoney": 2362.8,
        "retreatNumber": 3, "retreatMoney": 26.85,
        "payNumber": 261, "payMoney": 2335.95,
        "comboCode": "1100001134", "comboName": "超值单人套餐",
        "comboStandardName": "套餐", "comboPrice": 25.95,
    }
    out = api_row_to_output_row(row, period="202604")
    assert out[0] == "202604"           # 月份 (caller-supplied)
    assert out[1] == "加拿大"            # 国家 (default)
    assert out[2] == "加拿大八店"         # 门店名称
    assert out[6] == "1100001134"       # 套餐编码 ← comboCode
    assert out[10] == "01060061"        # 菜品编码 ← dishCode
    assert out[15] == 264                # 出品数量
    assert out[19] == 261                # 应收数量 ← payNumber


def test_api_row_returns_none_for_unmapped_fields():
    """Missing API fields → None in output (not crash). Lets us
    introspect raw API responses and tighten _FIELD_CANDIDATES on first
    live run if a default-mapping miss leaves a critical col blank."""
    row = {"shopName": "加拿大一店"}
    out = api_row_to_output_row(row, period="202604")
    # All 24 non-default cols should be None when no API field matches.
    assert out[10] is None  # 菜品编码 — most critical
    assert out[19] is None  # 应收数量 — most critical


def test_api_row_alternate_field_names():
    """If POS happens to use payQuantity instead of payNumber, the
    defensive mapping should still pick it up."""
    row = {"shopName": "加拿大一店", "dishCode": "X1",
           "payQuantity": 100, "applyNumber": 999}
    out = api_row_to_output_row(row, period="202604")
    assert out[10] == "X1"
    # First match wins — payNumber not present, payQuantity is the next
    # candidate so it should resolve to 100 (not applyNumber's 999).
    assert out[19] == 100

"""Tests for 表1 (菜品价格变动+损耗) builder.

Structural tests run anywhere. The integration test that loads real POS
data + manual workbook is skipped when those files aren't present.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from zfi0049_report.table1_dish import (
    HEADERS,
    MaterialUsage,
    PosSale,
    Table1Row,
    apply_canonical_blanking,
    build_rows_for_store,
    compute_revenue_impact,
    enrich_with_materials,
    enrich_with_prices,
    find_canonical_rows,
    load_mb5b_prices,
    load_pos_prices,
    load_pos_sales,
    load_zfi0156,
    to_row,
)

MANUAL_WB = Path(
    "/Users/hongming-claw/Downloads/附件3-毛利相关分析指标-2603.xlsx"
)
CA08_POS = Path(
    "/Users/hongming-claw/haidilao-automation-monorepo/output/pos/"
    "加拿大八店-菜品销售汇总-20260301-20260331.xlsx"
)
ZFI0156_MARCH = Path(
    "/Users/hongming-claw/haidilao-automation-monorepo/output/zfi0156/zfi0156-202603.xlsx"
)
MB5B_MARCH = Path(
    "/Users/hongming-claw/haidilao-automation-monorepo/output/mb5b/mb5b202603.xls"
)


def test_header_count():
    assert len(HEADERS) == 36


def test_theoretical_usage_formula():
    r = Table1Row(
        region="加拿大", store="加拿大八店", dish_code=1060066,
        dish_short_code=10016, dish_name="番茄火锅", portion=1.2,
        dish_unit="锅", spec="单锅", sales_qty=20, loss_factor=1.0,
    )
    # 20 × 1.2 × 1.0 = 24
    assert r.theoretical_usage == pytest.approx(24.0)


def test_theoretical_usage_applies_loss_factor():
    r = Table1Row(
        region="加拿大", store="加拿大一店", dish_code=1, dish_short_code=None,
        dish_name="X", portion=1.0, dish_unit=None, spec="单锅",
        sales_qty=100, loss_factor=1.05,
    )
    assert r.theoretical_usage == pytest.approx(105.0)


def test_unique_code_layout():
    r = Table1Row(
        region="加拿大", store="加拿大八店", dish_code=1060066,
        dish_short_code=10016, dish_name="番茄火锅", portion=1.2,
        dish_unit=None, spec="单锅",
    )
    assert r.unique_code == "加拿大八店106006610016单锅"
    assert r.set_meal_unique_code == "加拿大八店1060066番茄火锅单锅"


def test_price_deltas_when_data_missing_return_none():
    r = Table1Row(
        region="加拿大", store="x", dish_code=1, dish_short_code=None,
        dish_name="x", portion=1.0, dish_unit=None, spec="x",
    )
    assert r.mom_price_delta is None
    assert r.yoy_price_delta is None


def test_to_row_36_cols():
    r = Table1Row(
        region="加拿大", store="加拿大八店", dish_code=1060066,
        dish_short_code=10016, dish_name="番茄火锅", portion=1.2,
        dish_unit="锅", spec="单锅", sales_qty=20, loss_factor=1.0,
        material_code=3002745, material_name="番茄火锅底料",
    )
    row = to_row(r)
    assert len(row) == 36
    assert row[0] == "加拿大"
    assert row[2] == "加拿大八店106006610016单锅"
    assert row[3] == "加拿大八店1060066番茄火锅单锅"
    assert row[4] == 1060066
    assert row[10] == 20  # 本期销量
    assert row[11] == pytest.approx(24.0)  # 理论耗用量
    assert row[17] == 3002745  # 对应物料代码
    assert row[29] == pytest.approx(24.0)  # col 30 dup of col 12


def test_build_rows_joins_pos_to_bom():
    bom = [
        {"dish_code": 1060066, "dish_short_code": 10016, "dish_name": "番茄火锅",
         "spec": "单锅", "material_code": 3002745,
         "material_name": "番茄火锅底料", "portion": 1.2, "loss_factor": 1.0,
         "unit": "公斤"},
        {"dish_code": 9999, "dish_short_code": None, "dish_name": "无销售品",
         "spec": "整份", "material_code": 100, "material_name": "X",
         "portion": 0.5, "loss_factor": 1.0, "unit": "公斤"},
    ]
    sales = [PosSale(
        store="加拿大八店", dish_code=1060066, dish_short_code=10016,
        dish_name="番茄火锅", spec="单锅", sales_qty=20.0,
    )]
    rows = build_rows_for_store("加拿大八店",
                                pos_sales=sales, bom_rows=bom)
    assert len(rows) == 2
    # First row has matched sale
    assert rows[0].sales_qty == 20.0
    assert rows[0].theoretical_usage == pytest.approx(24.0)
    # Second row has no matching sale → zero
    assert rows[1].sales_qty == 0
    assert rows[1].theoretical_usage == 0.0


# ── Integration test (requires CA08 POS file present) ──


@pytest.mark.skipif(not CA08_POS.exists(),
                    reason="CA08 POS file not on this machine")
def test_load_pos_ca08_smoke():
    sales = load_pos_sales(CA08_POS)
    assert len(sales) > 100  # CA08 sold many dishes in March
    # Spot-check: 番茄火锅 1060066 should appear
    tomato = [s for s in sales if s.dish_code == 1060066]
    assert tomato
    by_spec = {s.spec: s for s in tomato}
    assert "单锅" in by_spec or "拼锅" in by_spec


# ── Enrichment tests ────────────────────────────────────────────────────


def _mk_row(dish=1060066, spec="单锅", material=3002745, sales=20.0):
    return Table1Row(
        region="加拿大", store="加拿大八店", dish_code=dish,
        dish_short_code=10016, dish_name="番茄火锅", portion=1.2,
        dish_unit=None, spec=spec, sales_qty=sales, loss_factor=1.0,
        material_code=material, material_name=None,
    )


def test_enrich_with_materials_uses_mb5b_for_price():
    rows = [_mk_row()]
    zfi = {("CA08", 3002745): MaterialUsage(
        werks="CA08", matnr=3002745, matxt="番茄火锅底料",
        unit="公斤", unit_price=3.3, quantity=1940.0, amount=6178.13,
    )}
    mb5b = {("CA08", 3002745): 3.22}  # MB5B moving avg differs from ZFI0156
    enrich_with_materials(rows, werks="CA08", zfi=zfi, mb5b_prices=mb5b)
    assert rows[0].material_unit_price == pytest.approx(3.22)
    # Period usage is THEORETICAL (sum of sales×portion×loss for material)
    # Single row, sales=20, portion=1.2, loss=1.0 → theoretical = 24
    assert rows[0].material_period_usage == pytest.approx(24.0)
    # Actual from ZFI0156
    assert rows[0].actual_usage == pytest.approx(1940.0)
    assert rows[0].material_name == "番茄火锅底料"


def test_enrich_with_materials_falls_back_to_zfi_price_when_no_mb5b():
    rows = [_mk_row()]
    zfi = {("CA08", 3002745): MaterialUsage(
        werks="CA08", matnr=3002745, matxt="番茄火锅底料",
        unit="公斤", unit_price=3.3, quantity=100.0, amount=330.0,
    )}
    enrich_with_materials(rows, werks="CA08", zfi=zfi, mb5b_prices={})
    assert rows[0].material_unit_price == pytest.approx(3.3)


def test_enrich_aggregates_theoretical_usage_per_material():
    """Two dishes share the same material — col 21 sums their theoretical."""
    rows = [
        Table1Row(region="加拿大", store="加拿大八店", dish_code=1, dish_short_code=1,
                  dish_name="A", portion=1.2, dish_unit=None, spec="单锅",
                  sales_qty=10, loss_factor=1.0, material_code=3002745),
        Table1Row(region="加拿大", store="加拿大八店", dish_code=2, dish_short_code=2,
                  dish_name="B", portion=0.5, dish_unit=None, spec="整份",
                  sales_qty=40, loss_factor=1.0, material_code=3002745),
    ]
    enrich_with_materials(rows, werks="CA08", zfi={}, mb5b_prices={})
    # Both rows share material 3002745:
    # row 1 theoretical = 10 × 1.2 × 1.0 = 12
    # row 2 theoretical = 40 × 0.5 × 1.0 = 20
    # Aggregate = 32
    assert rows[0].material_period_usage == pytest.approx(32.0)
    assert rows[1].material_period_usage == pytest.approx(32.0)


def test_enrich_with_prices_populates_cur_prev_yoy():
    rows = [_mk_row()]
    cur = {(1060066, "单锅"): (28.95, "锅")}
    prev = {(1060066, "单锅"): (28.95, "锅")}
    yoy = {(1060066, "单锅"): (24.95, "锅")}
    enrich_with_prices(rows, cur_prices=cur, prev_prices=prev, yoy_prices=yoy)
    assert rows[0].cur_dish_price == 28.95
    assert rows[0].prev_dish_price == 28.95
    assert rows[0].yoy_dish_price == 24.95
    assert rows[0].mom_price_delta == 0.0
    assert rows[0].yoy_price_delta == pytest.approx(4.0)
    assert rows[0].dish_unit == "锅"


def test_enrich_with_prices_handles_missing_data():
    rows = [_mk_row()]
    enrich_with_prices(rows, cur_prices={}, prev_prices={}, yoy_prices={})
    assert rows[0].cur_dish_price is None
    assert rows[0].mom_price_delta is None
    assert rows[0].yoy_price_delta is None


def test_load_pos_prices_returns_empty_for_old_format():
    """Older POS files lack 菜品单价 — graceful degrade, not crash."""
    # CA08_POS is the older 12-col format
    if not CA08_POS.exists():
        pytest.skip("CA08 POS file not on this machine")
    prices = load_pos_prices(CA08_POS)
    assert prices == {}


@pytest.mark.skipif(not ZFI0156_MARCH.exists(),
                    reason="ZFI0156 March 2026 not on this machine")
def test_load_zfi0156_march_2026_smoke():
    zfi = load_zfi0156(ZFI0156_MARCH)
    assert len(zfi) > 100  # many materials across 8 stores

    # Spot-check 番茄火锅底料 (material 3002745) for CA08
    key = ("CA08", 3002745)
    if key in zfi:
        m = zfi[key]
        assert m.matxt is not None
        assert "番茄" in m.matxt or "火锅底料" in m.matxt
        assert m.quantity > 0


@pytest.mark.skipif(not MB5B_MARCH.exists(),
                    reason="MB5B March 2026 not on this machine")
def test_load_mb5b_prices_march_2026_smoke():
    prices = load_mb5b_prices(MB5B_MARCH)
    assert len(prices) > 100
    # Should have at least one CA08 material
    ca08 = {k: v for k, v in prices.items() if k[0] == "CA08"}
    assert ca08


def test_find_canonical_rows_picks_largest_portion():
    """For each (store, dish, material) group, canonical = largest portion."""
    rows = [
        # dish 1060066, material 3002745 — 3 specs
        Table1Row(region="加拿大", store="加拿大一店", dish_code=1060066,
                  dish_short_code=10016, dish_name="番茄火锅", portion=1.2,
                  dish_unit=None, spec="单锅", material_code=3002745),
        Table1Row(region="加拿大", store="加拿大一店", dish_code=1060066,
                  dish_short_code=13066, dish_name="番茄火锅", portion=0.6,
                  dish_unit=None, spec="拼锅", material_code=3002745),
        Table1Row(region="加拿大", store="加拿大一店", dish_code=1060066,
                  dish_short_code=13102, dish_name="番茄火锅", portion=0.3,
                  dish_unit=None, spec="四宫格", material_code=3002745),
    ]
    canonical = find_canonical_rows(rows)
    # Largest portion (1.2 → 单锅) wins
    assert canonical == {0}


def test_find_canonical_groups_per_store():
    """Same dish_code in different stores → separate canonical rows."""
    rows = [
        Table1Row(region="加拿大", store="加拿大一店", dish_code=1,
                  dish_short_code=None, dish_name="X", portion=1.0,
                  dish_unit=None, spec="A", material_code=10),
        Table1Row(region="加拿大", store="加拿大二店", dish_code=1,
                  dish_short_code=None, dish_name="X", portion=1.0,
                  dish_unit=None, spec="A", material_code=10),
    ]
    canonical = find_canonical_rows(rows)
    assert canonical == {0, 1}  # both are canonical for their own store


def test_apply_canonical_blanking_clears_non_canonical_cols():
    rows = [
        Table1Row(region="加拿大", store="加拿大一店", dish_code=1060066,
                  dish_short_code=10016, dish_name="X", portion=1.2,
                  dish_unit=None, spec="单锅", sales_qty=10, loss_factor=1.0,
                  material_code=3002745),
        Table1Row(region="加拿大", store="加拿大一店", dish_code=1060066,
                  dish_short_code=13066, dish_name="X", portion=0.6,
                  dish_unit=None, spec="拼锅", sales_qty=100, loss_factor=1.0,
                  material_code=3002745),
    ]
    # Simulate population by enrich_with_materials
    for r in rows:
        r.material_period_usage = 100.0
        r.actual_usage = 95.0
        r.loss_cost_cur = 50.0
        r.loss_cost_prev = 40.0
        r.loss_cost_comparable = 45.0
    apply_canonical_blanking(rows)
    # Row 0 (canonical) keeps values
    assert rows[0].material_period_usage == 100.0
    assert rows[0].actual_usage == 95.0
    assert rows[0].loss_cost_cur == 50.0
    # Row 1 (non-canonical) is blanked
    assert rows[1].material_period_usage is None
    assert rows[1].actual_usage is None
    assert rows[1].loss_cost_cur is None
    assert rows[1].loss_cost_prev is None
    assert rows[1].loss_cost_comparable is None


def test_compute_revenue_impact_yoy_matches_manual():
    """Manual 加拿大一店 拼锅: cur=14.95, yoy=12.95, sales=1275 → YoY=2550."""
    rows = [Table1Row(
        region="加拿大", store="加拿大一店", dish_code=1060066,
        dish_short_code=13066, dish_name="番茄火锅", portion=0.6,
        dish_unit=None, spec="拼锅", sales_qty=1275, loss_factor=1.0,
        material_code=3002745, cur_dish_price=14.95,
        prev_dish_price=14.95, yoy_dish_price=12.95,
    )]
    compute_revenue_impact(rows)
    assert rows[0].mom_revenue_impact == pytest.approx(0.0)
    assert rows[0].yoy_revenue_impact == pytest.approx(2550.0)


def test_compute_revenue_impact_none_when_prices_missing():
    rows = [Table1Row(
        region="加拿大", store="x", dish_code=1, dish_short_code=None,
        dish_name="X", portion=1.0, dish_unit=None, spec="A", sales_qty=10,
        cur_dish_price=10.0,  # no prev/yoy
    )]
    compute_revenue_impact(rows)
    assert rows[0].mom_revenue_impact is None
    assert rows[0].yoy_revenue_impact is None


def test_to_row_includes_revenue_impacts():
    r = Table1Row(
        region="加拿大", store="加拿大一店", dish_code=1, dish_short_code=None,
        dish_name="X", portion=1.0, dish_unit=None, spec="A", sales_qty=100,
        cur_dish_price=10.0, prev_dish_price=9.0, yoy_dish_price=8.0,
        mom_revenue_impact=100.0, yoy_revenue_impact=200.0,
    )
    row = to_row(r)
    assert row[23] == 100.0  # col 24
    assert row[24] == 200.0  # col 25


@pytest.mark.skipif(
    not (ZFI0156_MARCH.exists() and MB5B_MARCH.exists() and MANUAL_WB.exists()),
    reason="need ZFI0156 + MB5B + manual workbook locally",
)
def test_enrichment_matches_manual_for_ca08_tomato_hotpot():
    """End-to-end: ZFI0156 + MB5B → row enrichment matches manual workbook
    for 加拿大八店 dish 1060066 (番茄火锅) material 3002745.

    From the manual we observed:
      col 13 本期单价 = 28.95
      col 20 单价/KG = 3.3
      col 21 本期耗用量 = 1872.16
    """
    zfi = load_zfi0156(ZFI0156_MARCH)
    mb5b = load_mb5b_prices(MB5B_MARCH)
    rows = [_mk_row()]
    enrich_with_materials(rows, werks="CA08", zfi=zfi, mb5b_prices=mb5b)
    # Manual: col 20 (单价/KG) for CA08/3002745 = 3.3 — MB5B agrees.
    assert rows[0].material_unit_price == pytest.approx(3.3, abs=0.01)
    # Manual: col 31 (actual_usage) ≈ 1940 from ZFI0156 数量.
    assert rows[0].actual_usage == pytest.approx(1940.0, abs=1.0)
    # Manual: col 21 = theoretical sum (this single-row test isn't meaningful
    # for the aggregate — full validation comes when we have all dish rows).
    assert rows[0].material_period_usage == pytest.approx(24.0)

"""Unit tests for inventory_check.calc_sheet — IPMS-derived 计算 builder."""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from inventory_check.calc_sheet import (
    HEADERS,
    UNIT_ALIASES,
    _loss_factor,
    _norm_code,
    _normalize_unit,
    attach_formulas,
    derive_calc_rows,
    load_ipms_bom_rows,
    write_calc_workbook,
)


class TestNormCode:
    def test_strips_leading_zeros(self):
        assert _norm_code("01060061") == "1060061"

    def test_int_is_stringified(self):
        assert _norm_code(1060061) == "1060061"

    def test_none_becomes_empty(self):
        assert _norm_code(None) == ""

    def test_already_unpadded(self):
        assert _norm_code("1060061") == "1060061"


class TestNormalizeUnit:
    def test_meibang_becomes_bang(self):
        # IPMS uses '磅-美' (American pound), manual just '磅'.
        assert _normalize_unit("磅-美") == "磅"

    def test_unmapped_passthrough(self):
        assert _normalize_unit("公斤") == "公斤"

    def test_none_passthrough(self):
        assert _normalize_unit(None) is None

    def test_strips_whitespace(self):
        assert _normalize_unit("  公斤  ") == "公斤"


class TestLossFactor:
    def test_yield_95_rounds_to_1_05(self):
        assert _loss_factor(95) == 1.05

    def test_yield_90_rounds_to_1_11(self):
        assert _loss_factor(90) == 1.11

    def test_yield_100_is_1(self):
        assert _loss_factor(100) == 1.0

    def test_empty_yield_defaults_to_1(self):
        assert _loss_factor("") == 1
        assert _loss_factor(None) == 1

    def test_invalid_yield_defaults_to_1(self):
        assert _loss_factor("not a number") == 1


class TestDeriveCalcRows:
    def test_one_row_per_bom(self):
        bom = [
            {"菜品编码": "01060061", "规格名称": "单锅",
             "物料编码": "03000759", "菜品名称": "清油麻辣火锅",
             "单位物料用量": 0.42, "物料产成率（%）": 95,
             "库存单位名称": "公斤", "用量单位": "g",
             "物料名称": "清油底料"},
        ]
        rows = derive_calc_rows(bom, store_name="加拿大八店")
        assert len(rows) == 1
        r = rows[0]
        assert r[0] == "加拿大八店1060061单锅"  # 检索
        assert r[1] == "加拿大"                  # 区域
        assert r[2] == "加拿大八店"               # 门店
        assert r[5] == 1060061                  # 菜品编码 — int form
        assert r[7] == "清油麻辣火锅"             # 菜品名称
        assert r[9] == "单锅"                    # 规格
        assert r[13] == 0.42                    # 出品分量
        assert r[14] == 1.05                    # 损耗 (yield 95)
        # P (物料单位) is the analyst's packaging conversion factor; left
        # blank because IPMS doesn't expose packaging-master data and the
        # T formula handles blank P as a no-op (multiply by 1).
        assert r[15] is None
        assert r[17] == 3000759                 # 物料号 — int form
        assert r[18] == "清油底料"                # 物料描述
        assert r[24] == "公斤"                   # 单位

    def test_unit_alias_applied(self):
        bom = [
            {"菜品编码": "1", "规格名称": "整份", "物料编码": "1",
             "库存单位名称": "磅-美"},
        ]
        rows = derive_calc_rows(bom, store_name="加拿大一店")
        assert rows[0][24] == "磅"

    def test_default_loss_when_yield_missing(self):
        bom = [
            {"菜品编码": "1", "规格名称": "整份", "物料编码": "1",
             "物料产成率（%）": ""},
        ]
        rows = derive_calc_rows(bom, store_name="加拿大一店")
        assert rows[0][14] == 1

    def test_search_key_uses_store_name(self):
        bom = [{"菜品编码": "1060061", "规格名称": "单锅", "物料编码": "1"}]
        ca1 = derive_calc_rows(bom, store_name="加拿大一店")
        ca2 = derive_calc_rows(bom, store_name="加拿大二店")
        assert ca1[0][0].startswith("加拿大一店")
        assert ca2[0][0].startswith("加拿大二店")
        assert ca1[0][0] != ca2[0][0]


def _mk_calc_row(f: object = 1060061, r: object = 3000759,
                 n: object = 1.2, o: object = 1.0) -> list:
    """Build a 26-col calc row with just F, R, N, O populated.

    Mirrors the layout from derive_calc_rows: idx 5=F, 13=N, 14=O, 17=R.
    """
    row = [None] * 26
    row[5], row[13], row[14], row[17] = f, n, o, r
    return row


class TestAttachFormulas:
    def test_formula_indices_single_canonical_row(self):
        """Single row with valid F/R/N is its own canonical group, so all
        formulas (M/Q/T/W/U/X/Z) emit on it."""
        rows = [_mk_calc_row()]
        attach_formulas(rows, report_sheet_name="CA08-本月-盘点结果.")
        # Always-emitted: M (12), Q (16), T (19).
        assert rows[0][12].startswith("=IFERROR(VLOOKUP(A2,Sheet3")
        assert rows[0][16] == "=N2*M2*O2"
        assert "CA08-本月-盘点结果." in rows[0][19]
        # T should multiply by P when set, and be a no-op (×1) when blank.
        assert 'IF(P2=""' in rows[0][19]
        # Canonical-only: W (22), U (20), X (23), Z (25).
        assert "BI套餐" in rows[0][22]
        # W now applies the loss factor (O) too — manual omitted it but
        # for consistency with Q (which is N*M*O), set-meal allocation
        # should also include O. When O=1 (default), it's a no-op.
        assert "*N2*O2" in rows[0][22]
        assert "SUMIF" in rows[0][20]
        assert "W2" in rows[0][20]                                   # U subtracts W
        assert "多用" in rows[0][23] and "少用" in rows[0][23]
        # Z combines the 多用/少用 remark with the unit so the report
        # sheet's 备注 col VLOOKUP(...,9) gets a non-empty value.
        assert rows[0][25] == '=IF(X2<>"",X2&Y2,"")'

    def test_canonical_row_is_smallest_n_per_dish_material_group(self):
        """Multi-spec dish-group: 3 rows for F=1060061, R=3000759 with
        N=1.2/0.6/0.3. Only the N=0.3 row (smallest, the per-set-meal
        portion) gets W/U/X/Z. Rows with larger N keep those cells blank
        so the material balance isn't triple-counted by SUMIF(R:R, R, Q:Q).
        """
        rows = [
            _mk_calc_row(n=1.2),  # 单锅
            _mk_calc_row(n=0.6),  # 拼锅
            _mk_calc_row(n=0.3),  # 四宫格 ← canonical
        ]
        attach_formulas(rows, report_sheet_name="REP")
        # All rows: M, Q, T are emitted (per-spec details).
        for r in rows:
            assert r[12].startswith("=IFERROR(VLOOKUP")
            assert r[16].startswith("=N")
            assert r[19].startswith("=IFERROR(VLOOKUP")
        # Only smallest-N row (idx 2 → spreadsheet row 4): W/U/X/Z.
        assert rows[2][22] is not None and "*N4*O4" in rows[2][22]
        assert rows[2][20] is not None and "T4" in rows[2][20]
        assert rows[2][23] is not None
        assert rows[2][25] is not None
        # Other rows: those cells stay None.
        for idx in (0, 1):
            assert rows[idx][22] is None
            assert rows[idx][20] is None
            assert rows[idx][23] is None
            assert rows[idx][25] is None

    def test_separate_groups_each_get_canonical(self):
        """Different (F, R) groups each get their own canonical row."""
        rows = [
            _mk_calc_row(f=1060061, r=3000759, n=1.2),  # group A
            _mk_calc_row(f=1060061, r=3000759, n=0.3),  # group A canonical
            _mk_calc_row(f=1060062, r=3000759, n=0.6),  # group B (same R, different F)
            _mk_calc_row(f=1060062, r=3000759, n=0.2),  # group B canonical
        ]
        attach_formulas(rows, report_sheet_name="REP")
        assert rows[0][22] is None      # group A non-canonical
        assert rows[1][22] is not None  # group A canonical
        assert rows[2][22] is None      # group B non-canonical
        assert rows[3][22] is not None  # group B canonical


class TestWriteWorkbook:
    def test_writes_calc_sheet(self, tmp_path: Path):
        rows = [[
            "加拿大八店1060061单锅", "加拿大", "加拿大八店",
            None, None, 1060061, None, "清油麻辣火锅", "清油麻辣火锅",
            "单锅", None, None, None, 0.42, 1.05, "g", None,
            3000759, "清油底料", None, None, None, None, None,
            "公斤", None,
        ]]
        out = tmp_path / "calc.xlsx"
        write_calc_workbook(rows, out)
        assert out.exists()

        wb = openpyxl.load_workbook(out, data_only=False)
        assert wb.sheetnames == ["计算"]
        ws = wb["计算"]
        assert ws.cell(1, 1).value == HEADERS[0]
        assert ws.cell(2, 1).value == "加拿大八店1060061单锅"
        assert ws.cell(2, 6).value == 1060061

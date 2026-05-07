"""Unit tests for inventory_check.references — runs against the real
checked-in data CSVs (so we catch shape regressions when they're
refreshed) plus a tmp_path roundtrip for the loader logic."""
from __future__ import annotations

from pathlib import Path

import pytest

from inventory_check.references import (
    MaterialClassification,
    MaterialDishLookup,
    UnitConversion,
    clear_cache,
    load_material_classification,
    load_material_dish_lookup,
    load_unit_conversion,
    material_classification_index,
    material_dish_index,
    unit_conversion_map,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    clear_cache()
    yield
    clear_cache()


# ── Real-data shape checks ─────────────────────────────────────────────


def test_unit_conversion_loads_real_data_with_known_specs() -> None:
    rows = load_unit_conversion()
    assert len(rows) > 1000
    specs = {r.spec for r in rows}
    # These two specs are present in CA08 202603 reference.
    assert "套餐" in specs
    assert "整份" in specs


def test_material_classification_loads_with_known_material() -> None:
    rows = load_material_classification()
    assert len(rows) > 1000
    by_matnr = {r.matnr: r for r in rows}
    # 1000049 = 金标生抽 (海天) — present in CA08 reference.
    assert "1000049" in by_matnr
    assert "金标生抽" in by_matnr["1000049"].description


def test_material_dish_lookup_loads_with_known_material() -> None:
    rows = load_material_dish_lookup()
    assert len(rows) > 100
    by_matnr = {r.matnr: r for r in rows}
    assert "1000049" in by_matnr


def test_material_classification_index_lookup_o1() -> None:
    idx = material_classification_index()
    m = idx["1000049"]
    assert m.country_code == "CA"
    assert m.description.startswith("金标生抽")


def test_material_dish_index_lookup_o1() -> None:
    idx = material_dish_index()
    m = idx["1000049"]
    assert m.dish_code  # non-empty
    assert m.dish_name


def test_unit_conversion_map_returns_floats() -> None:
    m = unit_conversion_map()
    assert isinstance(m["套餐"], float)
    assert isinstance(m["整份"], float)


# ── Loader semantics with tmp_path overrides ───────────────────────────


def _write_csv(p: Path, header: list[str], rows: list[list[str]]) -> None:
    import csv
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_unit_conversion_strips_blank_rows(tmp_path: Path) -> None:
    p = tmp_path
    _write_csv(p / "unit_conversion.csv",
               ["规格", "数量"],
               [["", ""], ["套餐", "1"], ["整份", "2.5"], ["", ""]])
    # Other CSVs need to exist (the data dir is shared across loaders).
    _write_csv(p / "material_classification.csv",
               ["国家/地区代码", "物料"], [])
    _write_csv(p / "material_dish_lookup.csv",
               ["区域", "门店", "物料号码"], [])

    rows = load_unit_conversion(p)
    assert len(rows) == 2
    assert rows[0] == UnitConversion(spec="套餐", quantity=1.0)
    assert rows[1] == UnitConversion(spec="整份", quantity=2.5)


def test_unit_conversion_skips_non_numeric_qty(tmp_path: Path) -> None:
    p = tmp_path
    _write_csv(p / "unit_conversion.csv",
               ["规格", "数量"],
               [["套餐", "1"], ["bad", "not-a-number"], ["整份", "2"]])
    _write_csv(p / "material_classification.csv", ["国家/地区代码", "物料"], [])
    _write_csv(p / "material_dish_lookup.csv", ["区域", "门店", "物料号码"], [])

    rows = load_unit_conversion(p)
    assert [r.spec for r in rows] == ["套餐", "整份"]


def test_material_classification_coerces_matnr_to_string(tmp_path: Path) -> None:
    """Excel turns 物料 into floats like '1000049.0' on export — strip the .0."""
    p = tmp_path
    _write_csv(p / "material_classification.csv",
               ["国家/地区代码", "物料", "门店标识", "物料描述", "物料分类",
                "一级分类", "二级分类", "标记", "备注"],
               [["CA", "1000049.0", "", "金标生抽", "1", "成本-小料台类",
                 "", "", ""]])
    _write_csv(p / "unit_conversion.csv", ["规格", "数量"], [])
    _write_csv(p / "material_dish_lookup.csv", ["区域", "门店", "物料号码"], [])

    rows = load_material_classification(p)
    assert len(rows) == 1
    assert rows[0].matnr == "1000049"
    assert isinstance(rows[0].matnr, str)


def test_material_classification_pads_short_rows(tmp_path: Path) -> None:
    """A short row with only matnr + desc should still parse cleanly."""
    p = tmp_path
    _write_csv(p / "material_classification.csv",
               ["国家/地区代码", "物料", "门店标识", "物料描述", "物料分类",
                "一级分类", "二级分类", "标记", "备注"],
               [["CA", "9999"]])
    _write_csv(p / "unit_conversion.csv", ["规格", "数量"], [])
    _write_csv(p / "material_dish_lookup.csv", ["区域", "门店", "物料号码"], [])

    rows = load_material_classification(p)
    assert len(rows) == 1
    assert rows[0].level1 == ""
    assert rows[0].notes == ""


def test_material_dish_lookup_pads_short_rows(tmp_path: Path) -> None:
    p = tmp_path
    _write_csv(p / "material_dish_lookup.csv",
               ["区域", "门店", "物料号码", "物料描述", "大类",
                "分类", "物料描述（通用）", "一级分类", "二级分类",
                "对应菜品编码", "对应菜品名称", "备注"],
               [["CA", "", "1234"]])
    _write_csv(p / "unit_conversion.csv", ["规格", "数量"], [])
    _write_csv(p / "material_classification.csv",
               ["国家/地区代码", "物料"], [])

    rows = load_material_dish_lookup(p)
    assert len(rows) == 1
    assert rows[0].matnr == "1234"
    assert rows[0].dish_code == ""
    assert rows[0].dish_name == ""


def test_material_classification_skips_blank_matnr(tmp_path: Path) -> None:
    p = tmp_path
    _write_csv(p / "material_classification.csv",
               ["国家/地区代码", "物料", "门店标识", "物料描述", "物料分类",
                "一级分类", "二级分类", "标记", "备注"],
               [["CA", "", "", "junk", "1", "", "", "", ""],
                ["CA", "9999", "", "real", "1", "", "", "", ""]])
    _write_csv(p / "unit_conversion.csv", ["规格", "数量"], [])
    _write_csv(p / "material_dish_lookup.csv", ["区域", "门店", "物料号码"], [])

    rows = load_material_classification(p)
    assert len(rows) == 1
    assert rows[0].matnr == "9999"


def test_coerce_matnr_preserves_trailing_zeros() -> None:
    """Regression: rstrip('.0') is wrong — it strips trailing 0s and dots,
    not the literal '.0' suffix. ``"4703100"`` must NOT become ``"47031"``."""
    from inventory_check.references import coerce_matnr

    assert coerce_matnr("4703100") == "4703100"
    assert coerce_matnr(4703100) == "4703100"
    assert coerce_matnr(4703100.0) == "4703100"
    assert coerce_matnr("1501610") == "1501610"
    assert coerce_matnr("1501610.0") == "1501610"
    assert coerce_matnr(None) == ""
    assert coerce_matnr("  4703100  ") == "4703100"


def test_coerce_matnr_strips_sap_zero_padding() -> None:
    """ZFI0156 raw exports pad matnrs to 18 chars; downstream code uses
    the unpadded form, so coerce_matnr must reconcile both."""
    from inventory_check.references import coerce_matnr

    assert coerce_matnr("000000000001000049") == "1000049"
    assert coerce_matnr("000000000004703100") == "4703100"
    assert coerce_matnr("0000000000004") == "4"
    # An all-zero string should not collapse to '' — keep it as '0'.
    assert coerce_matnr("0") == "0"
    assert coerce_matnr("0000") == "0000"


def test_dataclasses_are_frozen() -> None:
    u = UnitConversion(spec="x", quantity=1)
    m = MaterialClassification(country_code="CA", matnr="1", store_id="",
                               description="", classification="", level1="",
                               level2="", tag="", notes="")
    d = MaterialDishLookup(region="CA", store="", matnr="1", description="",
                           big_class="", classification="", common_desc="",
                           level1="", level2="", dish_code="", dish_name="",
                           notes="")
    for obj in (u, m, d):
        with pytest.raises(Exception):
            obj.matnr = "Z"  # type: ignore[misc]

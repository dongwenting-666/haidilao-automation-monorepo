"""Static reference tables for inventory-check.

These tables are checked into the repo as CSVs under
``projects/inventory-check/data/`` so the pipeline can run without a
fresh manual workbook every month. See ``data/README.md`` for the
refresh process.

NOT static (handled elsewhere): ``BI套餐`` is monthly data with a
``月份`` column — it's a per-month source, not a reference.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator


_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class UnitConversion:
    spec: str       # 规格 — e.g. "套餐", "整份"
    quantity: float  # 数量


@dataclass(frozen=True)
class MaterialClassification:
    """Row from 分类 sheet — material → category lookup."""

    country_code: str    # 国家/地区代码
    matnr: str           # 物料 (material number)
    store_id: str        # 门店标识 (often blank)
    description: str     # 物料描述
    classification: str  # 物料分类 (numeric code as string)
    level1: str          # 一级分类 (e.g. "成本-小料台类")
    level2: str          # 二级分类
    tag: str             # 标记 (e.g. "6月新增")
    notes: str           # 备注


@dataclass(frozen=True)
class MaterialDishLookup:
    """Row from 对照表 sheet — material → dish code mapping."""

    region: str          # 区域
    store: str           # 门店
    matnr: str           # 物料号码
    description: str     # 物料描述
    big_class: str       # 大类
    classification: str  # 分类
    common_desc: str     # 物料描述（通用）
    level1: str          # 一级分类
    level2: str          # 二级分类
    dish_code: str       # 对应菜品编码
    dish_name: str       # 对应菜品名称
    notes: str           # 备注


def _data_dir(override: Path | None = None) -> Path:
    return Path(override) if override else _DATA_DIR


def _read_csv(path: Path) -> Iterator[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = csv.reader(f)
        next(rows, None)  # skip header
        for row in rows:
            yield row


def _coerce_str(v: str) -> str:
    return v.strip()


def coerce_matnr(v: object) -> str:
    """Normalise a material number to a string key.

    Material numbers come in mixed types from xlsx/CSV/MB5B/SAP sources:
    int, float (e.g. ``4703100.0`` from xlsx parsing), zero-padded
    string (e.g. ``"000000000001000049"`` from ZFI0156 raw exports),
    or plain string. We always return a string so downstream dict
    lookups don't care about the input type.

    Important: do NOT use ``rstrip(".0")`` — that strips trailing zeros
    from any matnr ending in 0 (``"4703100"`` → ``"47031"``). Use
    ``removesuffix(".0")`` to drop the literal ``.0`` ending only.

    Leading zeros are stripped (``"000000000001000049"`` → ``"1000049"``)
    so an 18-character SAP-padded matnr matches the unpadded form MB5B
    and Fiori use. An all-zero matnr stays as ``"0"`` rather than
    collapsing to the empty string.
    """
    if v is None:
        return ""
    s = str(v).strip()
    s = s.removesuffix(".0")
    if s and set(s) != {"0"}:
        s = s.lstrip("0")
    return s


# Backwards-compat alias for the older internal name.
_coerce_matnr = coerce_matnr


@lru_cache(maxsize=None)
def load_unit_conversion(data_dir: Path | None = None) -> tuple[UnitConversion, ...]:
    """Load the 折算数量 lookup."""
    path = _data_dir(data_dir) / "unit_conversion.csv"
    rows = []
    for r in _read_csv(path):
        if len(r) < 2 or not r[0].strip():
            continue
        try:
            qty = float(r[1])
        except (ValueError, IndexError):
            continue
        rows.append(UnitConversion(spec=_coerce_str(r[0]), quantity=qty))
    return tuple(rows)


@lru_cache(maxsize=None)
def unit_conversion_map(data_dir: Path | None = None) -> dict[str, float]:
    """``规格 → 数量`` dict; later entries with the same spec win.

    Useful for dish-spec-to-quantity multiplication during 折算 (conversion).
    """
    out: dict[str, float] = {}
    for u in load_unit_conversion(data_dir):
        out[u.spec] = u.quantity
    return out


@lru_cache(maxsize=None)
def load_material_classification(
    data_dir: Path | None = None,
) -> tuple[MaterialClassification, ...]:
    """Load the 分类 sheet — one row per material."""
    path = _data_dir(data_dir) / "material_classification.csv"
    rows = []
    for r in _read_csv(path):
        if len(r) < 2 or not r[1].strip():
            continue
        # pad to 9 cols
        r = list(r) + [""] * max(0, 9 - len(r))
        rows.append(MaterialClassification(
            country_code=_coerce_str(r[0]),
            matnr=_coerce_matnr(r[1]),
            store_id=_coerce_str(r[2]),
            description=_coerce_str(r[3]),
            classification=_coerce_str(r[4]),
            level1=_coerce_str(r[5]),
            level2=_coerce_str(r[6]),
            tag=_coerce_str(r[7]),
            notes=_coerce_str(r[8]),
        ))
    return tuple(rows)


@lru_cache(maxsize=None)
def material_classification_index(
    data_dir: Path | None = None,
) -> dict[str, MaterialClassification]:
    """Index by 物料 (Matnr) for O(1) lookup."""
    return {m.matnr: m for m in load_material_classification(data_dir)}


@lru_cache(maxsize=None)
def load_material_dish_lookup(
    data_dir: Path | None = None,
) -> tuple[MaterialDishLookup, ...]:
    """Load the 对照表 sheet — material → dish code mappings."""
    path = _data_dir(data_dir) / "material_dish_lookup.csv"
    rows = []
    for r in _read_csv(path):
        if len(r) < 3 or not r[2].strip():
            continue
        r = list(r) + [""] * max(0, 12 - len(r))
        rows.append(MaterialDishLookup(
            region=_coerce_str(r[0]),
            store=_coerce_str(r[1]),
            matnr=_coerce_matnr(r[2]),
            description=_coerce_str(r[3]),
            big_class=_coerce_str(r[4]),
            classification=_coerce_str(r[5]),
            common_desc=_coerce_str(r[6]),
            level1=_coerce_str(r[7]),
            level2=_coerce_str(r[8]),
            dish_code=_coerce_str(r[9]),
            dish_name=_coerce_str(r[10]),
            notes=_coerce_str(r[11]),
        ))
    return tuple(rows)


@lru_cache(maxsize=None)
def material_dish_index(
    data_dir: Path | None = None,
) -> dict[str, MaterialDishLookup]:
    """Index by 物料号码 — last entry wins on collision."""
    return {m.matnr: m for m in load_material_dish_lookup(data_dir)}


def clear_cache() -> None:
    """Drop the lru_cache — call this in tests that swap data_dir."""
    load_unit_conversion.cache_clear()
    unit_conversion_map.cache_clear()
    load_material_classification.cache_clear()
    material_classification_index.cache_clear()
    load_material_dish_lookup.cache_clear()
    material_dish_index.cache_clear()

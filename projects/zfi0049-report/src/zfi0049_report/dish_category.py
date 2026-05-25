"""Dish → report-category mapping for the 细分毛利率表.

The manual workbook breaks gross margin out across seven categories:
锅底类 / 荤菜类 / 素菜类 / 酒水类 / 小料台类-酱料水果 / 小吃类 / 其他类（如有）.

POS 红火台 exports tag each dish with a 大类名称 / 子类名称 pair. We
map 大类 → report category (with 子类 as tie-breaker when 大类 alone is
ambiguous). Anything unmapped falls into 其他类（如有）.

Mapping verified against 加拿大八店 March 2026 POS (24 distinct
(大类, 子类) combinations seen).
"""
from __future__ import annotations


# Display order matches the manual workbook columns.
REPORT_CATEGORIES: list[str] = [
    "锅底类",
    "荤菜类",
    "素菜类",
    "酒水类",
    "小料台类-酱料水果",
    "小吃类",
    "其他类（如有）",
]

OTHER = "其他类（如有）"


# Primary mapping by POS 大类.
_DALEI_MAP: dict[str, str] = {
    "锅底类": "锅底类",
    "荤菜": "荤菜类",
    "素菜": "素菜类",
    "酒水饮料": "酒水类",
    "小吃甜品": "小吃类",
    "火锅周边": "小料台类-酱料水果",
    # 套餐 / 经典火锅菜 / 赠送及其他类 → 其他类（fallback）
}


def map_pos_to_report_category(
    dalei: str | None, zilei: str | None = None,
) -> str:
    """Return the report category for a POS (大类, 子类) pair.

    Lookup order: 大类 → primary map → fallback to 其他类. ``zilei`` is
    currently unused but kept in the signature so we can refine the map
    later (e.g. split 经典火锅菜 by 子类) without a signature change.
    """
    del zilei
    if dalei is None:
        return OTHER
    key = str(dalei).strip()
    return _DALEI_MAP.get(key, OTHER)

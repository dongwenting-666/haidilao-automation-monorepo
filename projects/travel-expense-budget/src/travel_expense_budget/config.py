"""Cost center → entity mapping and report configuration."""

from __future__ import annotations

from dataclasses import dataclass


# Travel expense GL accounts (差旅费)
TRAVEL_GL_PREFIXES = ("51011601", "51011602", "51011604", "51011605")

# KSB1 columns (0-indexed)
KSB1_COL_COST_CENTER = 2    # 成本中心
KSB1_COL_GL_CODE = 5        # 成本要素
KSB1_COL_CAD = 8            # 业务货币值 (transaction currency — CAD or USD)
KSB1_COL_CURRENCY = 9       # 交易货币 (CAD, USD, etc.)

# Default CAD → USD exchange rate (derived from SAP 2025 data: 0.695265)
DEFAULT_CAD_TO_USD = 0.695265

# QBI columns (0-indexed)
QBI_COL_STORE = 3            # 门店名称
QBI_COL_REVENUE = 14         # 营业收入(不含税)


@dataclass
class Entity:
    """A store or functional department in the report."""
    name: str
    section: str  # "营业门店" or "职能部门"
    cost_centers: list[str]  # KSB1 cost center codes


# Store cost centers: 945120X002 = 加拿大X店销售公共组
STORES = [
    Entity("加拿大一店", "营业门店", ["9451201002"]),
    Entity("加拿大二店", "营业门店", ["9451202002"]),
    Entity("加拿大三店", "营业门店", ["9451203002"]),
    Entity("加拿大四店", "营业门店", ["9451204002"]),
    Entity("加拿大五店", "营业门店", ["9451205002"]),
    Entity("加拿大六店", "营业门店", ["9451206002"]),
    Entity("加拿大七店", "营业门店", ["9451207002"]),
    Entity("加拿大八店", "营业门店", ["9451208002"]),
    Entity("加拿大九店", "营业门店", ["9451209002"]),
]

# Management/functional cost centers
DEPARTMENTS = [
    Entity("大区蒋冰遇（9451）", "职能部门", ["9451100006"]),
    Entity("统筹部-蒋冰遇（9400）", "职能部门", ["9400100019"]),
    Entity("加拿大人事部", "职能部门", ["9451100003"]),
    Entity("加拿大采购部", "职能部门", ["9451100005"]),
    Entity("加拿大厨政（9451）", "职能部门", ["9451100013"]),
    Entity("加拿大片区品牌部（9451）", "职能部门", ["9451100034"]),
    Entity("品牌管理部（9451）", "职能部门", ["9451100016"]),
    Entity("加拿大片区", "职能部门", ["9451100038"]),
]

ALL_ENTITIES = STORES + DEPARTMENTS

# QBI store names → entity name mapping
QBI_STORE_MAP = {
    "加拿大一店": "加拿大一店",
    "加拿大二店": "加拿大二店",
    "加拿大三店": "加拿大三店",
    "加拿大四店": "加拿大四店",
    "加拿大五店": "加拿大五店",
    "加拿大六店": "加拿大六店",
    "加拿大七店": "加拿大七店",
    "加拿大八店": "加拿大八店",
    "加拿大九店": "加拿大九店",
}

"""Store names, regions, time slots, and other constants."""

# Ordered store list (default column order in report)
STORES: list[str] = [
    "加拿大一店",
    "加拿大二店",
    "加拿大三店",
    "加拿大四店",
    "加拿大五店",
    "加拿大六店",
    "加拿大七店",
    "加拿大八店",
]

REGION_LABEL = "加拿大片区"

# Hypothetical competitor (假想敌) mapping: store → its designated benchmark store.
# Fixed values — do not change without business sign-off.
COMPETITOR: dict[str, str] = {
    "加拿大一店": "加拿大五店",
    "加拿大二店": "加拿大一店",
    "加拿大三店": "加拿大五店",
    "加拿大四店": "加拿大一店",
    "加拿大五店": "加拿大三店",
    "加拿大六店": "加拿大二店",
    "加拿大七店": "加拿大一店",
    "加拿大八店": "加拿大七店",
}

# Region groupings for Sheet 2 (同比数据)
WEST_STORES = ["加拿大一店", "加拿大二店", "加拿大七店"]
EAST_STORES = ["加拿大三店", "加拿大四店", "加拿大五店", "加拿大六店", "加拿大八店"]

# Validate that west + east covers exactly the same stores
assert set(WEST_STORES + EAST_STORES) == set(STORES), (
    "WEST_STORES + EAST_STORES must contain the same stores as STORES"
)

# Time slots (ordered)
TIME_SLOTS: list[str] = [
    "08:00-13:59",
    "14:00-16:59",
    "17:00-21:59",
    "22:00-(次)07:59",
]

# QBI sheet name for tax-excluded data
QBI_SHEET_DAILY = "海外门店营业数据日报_不含税_"
QBI_SHEET_TIME_PERIOD = "海外门店营业数据分时段_不含税_"

# QBI column names
COL_STORE = "门店名称"
COL_DATE = "日期"
COL_TIME_SLOT = "分时段"
COL_TABLES_ASSESSED = "营业桌数(考核)"
COL_TABLES_RAW = "营业桌数"
COL_TABLES_TAKEOUT = "营业桌数(考核)(外卖)"
COL_REVENUE = "营业收入(不含税)"
COL_CUSTOMERS = "就餐人数"
COL_TURNOVER = "翻台率(考核)"
COL_DISCOUNT = "优惠总金额(不含税)"

# Weekday names in Chinese
WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# Yuan-to-wan conversion divisor
WAN_DIVISOR = 10_000

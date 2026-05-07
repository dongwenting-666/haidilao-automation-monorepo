"""Monthly stocktake report (盘点结果) automation.

Pipeline (v1, CA08-only)
------------------------
1. **Fiori 盘点报表** (sap-fiori-crawler) — physical count entries
   per material (Menge/MengePd).
2. **POS dish-sales** (pos-crawler) — 红火台销售汇总 by store/month.
3. **(TODO) MB5B** — system inventory + monthly movement (the manual
   `本月系统单价mb5b` sheet). Needed to reproduce the manual file's
   adjusted 库存数量 / 盘点数量 numbers.
4. **(TODO) BOM/折算数量/对照表/分类** — static reference tables that
   today live in the manual workbook. May be drop-in files or fetched
   from IPMS.

Output: ``output/inventory-check/<store>-盘点结果-<YYYYMM>.xlsx``
"""
from inventory_check.dates import month_to_period, parse_month
from inventory_check.pipeline import build_inventory_report

__all__ = [
    "build_inventory_report",
    "month_to_period",
    "parse_month",
]

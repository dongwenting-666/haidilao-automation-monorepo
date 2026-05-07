# Static reference data

These CSVs are extracted from the manual `CA08-盘点结果-{YYYYMM}.xlsx`
workbook and are checked in so the inventory-check pipeline doesn't
depend on a fresh manual export every run.

| File | Source sheet | Rows | When to refresh |
|------|--------------|------|-----------------|
| `unit_conversion.csv` | `折算数量` | ~4317 | When new dish specs are added |
| `material_classification.csv` | `分类` | ~4047 | Periodically — has a `标记` column noting recent additions (e.g. "6月新增") |
| `material_dish_lookup.csv` | `对照表` | ~459 | When new materials are mapped to dish codes |

To refresh: drop a newer manual workbook into `~/Downloads/`, then run::

    uv run python -m inventory_check.refresh_reference_data \
        --src ~/Downloads/CA08-盘点结果-NEWER.xlsx

(That CLI is TBD — open issue.)

## What is NOT here

The **`BI套餐`** sheet (~1190 rows) is **monthly data**, not a static
reference — the `月份` column is `202603` (or whichever month). It needs
its own data source crawler, separate from these drop-ins.

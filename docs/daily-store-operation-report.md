# Daily Store Operation Report

Automated generation of a daily Excel report comparing Haidilao Canada store operations across current month, previous month, and previous year. Downloads data from Quick BI and produces a pixel-perfect 4-sheet Excel workbook.

## CLI Usage

```bash
# Full pipeline: download from QBI + generate report
uv run --project projects/daily-store-operation-report \
  python -m daily_store_operation_report.main 2026-02-10

# Skip download, use pre-downloaded files (auto-resolve by filename date)
uv run --project projects/daily-store-operation-report \
  python -m daily_store_operation_report.main 2026-02-10 --skip-download

# Explicit file paths (most reliable)
uv run --project projects/daily-store-operation-report \
  python -m daily_store_operation_report.main 2026-02-10 \
  --cur-daily output/qbi/海外门店经营日报数据_20260201_20260210.xlsx \
  --prev-daily output/qbi/海外门店经营日报数据_20260101_20260110.xlsx \
  --yoy-daily output/qbi/海外门店经营日报数据_20250201_20250210.xlsx \
  --cur-tp output/qbi/海外分时段报表_20260201_20260210.xlsx \
  --yoy-tp output/qbi/海外分时段报表_20250201_20250210.xlsx
```

### Options

| Flag | Description |
|------|-------------|
| `DATE` | Report date in YYYY-MM-DD (default: T-2, two days ago in Vancouver time) |
| `--skip-download` | Use pre-downloaded files from `--data-dir` |
| `--data-dir PATH` | Directory with QBI exports (default: `output/qbi/`) |
| `--output-dir PATH` | Output directory (default: `output/daily-report/`) |
| `--cur-daily` / `--prev-daily` / `--yoy-daily` | Explicit daily report files |
| `--cur-tp` / `--yoy-tp` | Explicit time-period report files |
| `--no-headless` | Show browser during QBI download |

### Environment Variables

- `QBI_USERNAME` — Quick BI LDAP username (required for download)
- `QBI_PASSWORD` — Quick BI LDAP password (required for download)

## Data Pipeline

### Downloads (5 QBI Reports)

| # | Report Type | Date Range | Purpose |
|---|------------|-----------|---------|
| 1 | 门店经营日报数据 | 1st of month → report date | Current month MTD |
| 2 | 门店经营日报数据 | 1st of prev month → same day | Previous month same period |
| 3 | 门店经营日报数据 | 1st of same month last year → same day last year | YoY same period |
| 4 | 分时段营业数据 | 1st of month → report date | Current month time slots |
| 5 | 分时段营业数据 | 1st of same month last year → same day last year | YoY time slots |

All read from the `不含税` (tax-excluded) sheet. A single `QBISession` is used for all 5 downloads.

### Transform Pipeline

```
5 QBI XLSX files
    │
    ▼
_load_daily / _load_time_period (via excel_utils.load_data_rows)
    │  ↓ _normalize_date() handles datetime/string dates from openpyxl
    ▼
_load_all_raw_data() → RawData dataclass (26 typed fields)
    │  ↓ _sum_by_store, _avg_turnover_by_store, _last_day_by_store, etc.
    ▼
_build_store_metrics() → StoreMetrics per store
    │  ↓ div_or_zero for safe division, WAN_DIVISOR for 万 conversion
    ▼
ReportData (dates + 8 StoreMetrics)
    │
    ▼
4 sheet builders → openpyxl Workbook
    │  ↓ _format_numbers() rounds all floats to 2 decimals
    ▼
database_report_YYYY_MM_DD.xlsx
```

## Output Sheets

### Sheet 1: 对比上月表 (MoM Detail)

Gold theme. Compares current month vs previous month across 4 sections:
- 桌数(考核) — table counts, today vs MTD vs previous month
- 收入(不含税-万加元) — revenue in 万, targets, completion rates, discounts
- 单桌消费(不含税) — per-table and per-capita spending
- 翻台率 — turnover rate rankings (today + MTD)

### Sheet 2: 同比数据 (YoY Summary)

Gold theme with region grouping (西部 3 stores, 东部 5 stores). Four comparison sections: tables, turnover rate, revenue, per-table spending. Each section shows current, YoY, diff, and growth rate.

### Sheet 3: 对比上年表 (YoY Detail)

Blue theme. Same layout as Sheet 1 but comparing against previous year instead of previous month. Shares implementation with Sheet 1 via `comparison_sheet.py`.

### Sheet 5: 假想敌翻台率对比 (Competitor Turnover Comparison)

Green/teal theme. Compares each store's turnover rate against its designated competitor store.

| Column | Content |
|--------|---------|
| 门店 | Store name |
| 假想敌 | Competitor store name |
| {prev_month}月份翻台率差异 | Full previous-month turnover delta (store − competitor) |
| {cur_month}月截止目前门店翻台率 | Current month MTD turnover rate (store) |
| {cur_month}月截止目前假想敌翻台率 | Current month MTD turnover rate (competitor) |
| 差异对比 | MTD delta (store − competitor) |

Month labels are dynamic (e.g. "2月" / "3月"). Competitor store assignments are configured in the DB via `/admin/competitors`.

### Sheet 4: 分时段-上报 (Time-Period Breakdown)

Per-store colors with 4 time slots per store. Shows turnover rates and table counts broken down by:
- 08:00-13:59, 14:00-16:59, 17:00-21:59, 22:00-(次)07:59

Includes per-store subtotals (gray), region total (navy), and comparisons against targets and YoY same-weekday.

## Architecture

### Parameterized Comparison Sheets

`comparison_sheet.py` eliminates ~85% duplication between MoM and YoY detail sheets:

```python
@dataclass
class SheetTheme:
    title_font, header_font, header_fill
    section_a_fill, section_b_fill, highlight_fill

@dataclass
class ComparisonConfig:
    sheet_name, comp_type, comp_label
    get_comp_tables, get_comp_raw_tables
    get_comp_revenue_wan, get_comp_per_table
    theme: SheetTheme
```

`mom.py` and `yoy_detail.py` are thin wrappers (~47 lines each) that configure the theme and data accessors.

### Key Computations

- Revenue in 万: `raw_revenue / 10_000`, rounded to 2 decimals at display time
- 标准时间进度: `day_of_month / days_in_month`
- 目标完成率: `mtd_revenue / target * 100`
- 去年同周同日: `report_date - timedelta(days=364)` (52 weeks = same weekday)
- Region turnover average: excludes stores with `mtd_tables == 0` to avoid dilution
- Time-slot daily turnover = sum of per-slot rates (each slot is independent)

### Targets & Competitor Config — DB-Backed

Targets (revenue + turnover rate) and competitor store mappings are stored in PostgreSQL, managed via the admin UI:

- **Targets**: `/admin/targets` — set monthly revenue (万 CAD) and turnover rate per time slot per store
- **Competitors**: `/admin/competitors` — set competitor store name for each of the 8 stores

The `--targets` CLI flag is no longer needed. The report reads from the DB via `server.db.get_targets_for_report()`.

**Missing config guard (`_check_config`):** Before downloading data, the report checks that both targets and competitor config exist for the requested month. If either is missing, it:
1. Sends a Lark alert to the configured notification target
2. Prints the admin URL: https://haidilao.wanghongming.xyz/admin
3. Exits with a non-zero code (no QBI download attempted)

This guard requires `DATABASE_URL` to be set and the server package to be importable. When running standalone (without server), ensure the monorepo is installed via `uv sync`.

**Legacy `targets.json` schema** (for reference — no longer used in production):

```json
{
  "2026-02": {
    "revenue": { "加拿大一店": 50.0 },
    "turnover_rate": {
      "加拿大一店": {
        "08:00-13:59": 1.12, "14:00-16:59": 0.71,
        "17:00-21:59": 1.98, "22:00-(次)07:59": 0.80,
        "total": 4.61
      }
    }
  }
}
```

## Dependencies

- `qbi-crawler` — Browser automation for QBI downloads
- `excel-utils` — `load_data_rows()` for reading QBI exports, `create_workbook()` for output
- `openpyxl` — Direct styling (merged cells, per-cell fills, conditional fonts)
- `python-dotenv` — `.env` loading for QBI credentials

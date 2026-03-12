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
| `DATE` | Report date in YYYY-MM-DD (default: yesterday) |
| `--skip-download` | Use pre-downloaded files from `--data-dir` |
| `--data-dir PATH` | Directory with QBI exports (default: `output/qbi/`) |
| `--output-dir PATH` | Output directory (default: `output/daily-report/`) |
| `--targets PATH` | Path to targets.json (default: bundled) |
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

### targets.json Schema

```json
{
  "2026-02": {
    "revenue": {
      "加拿大一店": 50.0,
      "加拿大二店": 45.0
    },
    "turnover_rate": {
      "加拿大一店": {
        "08:00-13:59": 1.12,
        "14:00-16:59": 0.71,
        "17:00-21:59": 1.98,
        "22:00-(次)07:59": 0.80,
        "total": 4.61
      }
    }
  }
}
```

Missing month or store defaults to 0. Structure is validated at load time.

## Dependencies

- `qbi-crawler` — Browser automation for QBI downloads
- `excel-utils` — `load_data_rows()` for reading QBI exports, `create_workbook()` for output
- `openpyxl` — Direct styling (merged cells, per-cell fills, conditional fonts)
- `python-dotenv` — `.env` loading for QBI credentials

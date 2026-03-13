# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Monorepo for Haidilao paperwork automations. Uses **uv workspaces** with Python >= 3.13 and **hatchling** as the build backend.

## Repository Layout

- `libs/` — Shared libraries consumed by projects (e.g., `sap-gui`, `ollama-client`, `qbi-crawler`, `excel-utils`)
- `projects/` — Automation projects (e.g., `ksb1-accounting-check`, `ksb1-accounting-check-gui`, `daily-store-operation-report`)
- Each package follows `src/` layout: `src/<package_name>/`
- `output/` — Default export destination (gitignored), organized by tool (`output/ksb1/`, `output/qbi/`, `output/daily-report/`)

Projects depend on libs via workspace references (`[tool.uv.sources]` in their `pyproject.toml`).

## SAP GUI Library Structure

```
libs/sap-gui/src/sap_gui/
    errors.py          # Exception hierarchy (SAPGuiError, SAPConnectionError, etc.)
    session.py         # COM connection (SAPSession, SAPSessionManager)
    navigation.py      # Transaction/field/button helpers (SAPNavigator)
    export.py          # File export (SAPExporter — ALV grid + classic list)
    processes/         # Process-specific automation modules
        ksb1/          # KSB1 cost center report export
            __init__.py        # execute(), run(), helpers
            cost_centers.txt   # Default cost center list
```

## QBI Crawler Library Structure

```
libs/qbi-crawler/src/qbi_crawler/
    auth.py            # QBISession — Playwright browser lifecycle + LDAP login
    constants.py       # BASE_URL for Quick BI portal
    dashboard.py       # Report navigation, date filtering, XLSX export
    errors.py          # Exception hierarchy (QBIError, QBILoginError, QBITimeoutError)
    py.typed           # PEP 561 marker
```

### Key Design Decisions

- **Playwright** (not requests/Selenium) because Quick BI is a React SPA with JS-rendered content
- **Direct URL navigation** with menuIds instead of sidebar clicks (avoids iframe detachment)
- **Keyboard input** for Ant Design DatePicker (not `fill()` — elements are not directly editable)
- **Auto-installs Chromium** on first session start (thread-safe, skipped after first success)
- Reports supported: `REPORT_DAILY`, `REPORT_TIME_PERIOD`, `REPORT_24H`
- Default output subdirectory: `output/qbi/`

## Excel Utils Library Structure

```
libs/excel-utils/src/excel_utils/
    reader.py          # load_data_rows(), load_mapping() — XLSX reading
    style.py           # BOLD_FONT, set_header_row(), auto_size_columns()
    workbook.py        # create_workbook(), write_data_sheet(), copy_sheet_data(), truncate_sheet_name()
    py.typed           # PEP 561 marker
```

Shared openpyxl utilities for reading, writing, and styling Excel files. Projects should depend on this via `excel-utils = { workspace = true }` instead of using openpyxl directly.

## KSB1 Accounting Check Structure

```
projects/ksb1-accounting-check/src/ksb1_accounting_check/
    main.py            # CLI entry point (argparse, SAP download + report generation)
    analyze.py         # Data loading, enrichment, per-store comparison, XLSX report
    rules.py           # Deterministic rule-based analysis
    llm.py             # Optional LLM enhancement (explains WHY findings exist)
    prompt.md          # LLM enhancer prompt
    报表科目.xlsx       # Cost element → 报表科目 mapping spreadsheet
```

### Analysis Rules (`rules.py`)

The KSB1 accounting check uses deterministic rules for anomaly detection:
- **Skipped kemus**: `SKIP_KEMUS` — high-volume routine items excluded from analysis
- **Key cost elements**: `KEY_COST_ELEMENTS` — always reported when they change (threshold: 100 CAD)
- **General thresholds**: minimum absolute difference of 500 CAD **and** 20% change
- **Presence checks**: flags cost elements present in one month but absent in the other
- Uses `对象货币值` (object currency / local CAD) for amounts, not `报表货币值`

### LLM Enhancement (`llm.py`)

Optional hybrid approach — pass `--model qwen3:8b` (CLI) or select a model in the GUI:
- Rules detect anomalies deterministically; LLM explains *why* they exist
- Pre-computes grouped subtotals so LLM never does arithmetic
- Batching + retry logic with graceful fallback to rule-based observations
- `set_prompt_path()` API for overriding prompt file location (used by PyInstaller)

## KSB1 GUI Structure

```
projects/ksb1-accounting-check-gui/src/ksb1_accounting_check_gui/
    app.py             # tkinter GUI (credentials, settings, cost centers, log output)
    worker.py          # Background worker (SAP download + report generation)
    paths.py           # Resource path resolution (frozen vs dev mode)
    log_handler.py     # Thread-safe logging to tkinter Text widget
```

Build EXE: `cd projects/ksb1-accounting-check-gui && python -m PyInstaller ksb1_gui.spec --noconfirm`

## Daily Store Operation Report Structure

```
projects/daily-store-operation-report/src/daily_store_operation_report/
    main.py              # CLI entry point (argparse, --skip-download, explicit file paths)
    download.py          # QBI download orchestration (5 files via single session)
    dates.py             # Date range calculations (cur/prev/yoy periods, frozen dataclass)
    transform.py         # Raw QBI data → RawData → StoreMetrics → ReportData
    report.py            # Orchestrator: calls sheet builders, _format_numbers, saves workbook
    constants.py         # Store names, regions, time slots, QBI column names
    utils.py             # div_or_zero, comp_text, pct_str
    targets.json         # Monthly revenue + turnover rate targets per store
    sheets/
        styles.py        # All openpyxl fill/font/border constants + helpers (typed ws params)
        comparison_sheet.py  # Shared builder for MoM/YoY detail (SheetTheme + ComparisonConfig)
        mom.py           # Sheet 1: 对比上月表 (gold theme, thin config wrapper)
        yoy_summary.py   # Sheet 2: 同比数据 (region-grouped, gold theme)
        yoy_detail.py    # Sheet 3: 对比上年表 (blue theme, thin config wrapper)
        time_period.py   # Sheet 4: 分时段-上报 (per-store colors)
```

### Key Design Decisions

- **Parameterized comparison sheets** — `comparison_sheet.py` with `SheetTheme` + `ComparisonConfig` dataclasses eliminates ~85% duplication between MoM and YoY detail sheets
- **Typed raw data pipeline** — `RawData` dataclass (typed fields) → `StoreMetrics` per store → `ReportData` for all sheets
- **Date normalization** — `_normalize_date()` handles both `datetime` and string dates from openpyxl
- **Late formatting** — Raw floats stored in dataclasses; `_format_numbers()` rounds to 2 decimals at save time
- **Nonzero-store averaging** — Region turnover averages exclude stores with no data to avoid dilution

### Data Flow

Downloads 5 QBI reports (3 daily + 2 time-period) for current month, previous month same period, and previous year same period. All use the `不含税` sheet. Key fields: `营业桌数(考核)`, `营业收入(不含税)`, `就餐人数`, `优惠总金额(不含税)`, `翻台率(考核)`.

Revenue displayed in 万 (÷10000). Time progress = day_of_month / days_in_month. 去年同周同日 = report_date - 364 days. `compute_metrics()` accepts `DownloadedFiles` dataclass (not individual paths).

## Commands

```bash
# Install all dependencies
uv sync

# Run KSB1 export (defaults to previous month, output to <repo>/output/)
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Run KSB1 with LLM enhancement
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --model qwen3:8b

# Run KSB1 GUI (development mode)
python -m ksb1_accounting_check_gui

# Build KSB1 GUI EXE
cd projects/ksb1-accounting-check-gui && python -m PyInstaller ksb1_gui.spec --noconfirm

# Run tests for KSB1 accounting check
python -m pytest projects/ksb1-accounting-check/tests/ -v

# Add a dependency to a specific package
uv add --project libs/sap-gui <package>

# Run daily store operation report (downloads from QBI + generates Excel)
uv run --project projects/daily-store-operation-report python -m daily_store_operation_report.main 2026-02-10

# Run with pre-downloaded files (skip QBI login)
uv run --project projects/daily-store-operation-report python -m daily_store_operation_report.main 2026-02-10 --skip-download --data-dir output/qbi

# Install Playwright browser (required once for qbi-crawler)
playwright install chromium
```

## Key Conventions

- SAP GUI 770 must be open before running automations — `sap-gui` uses COM/ActiveX via `pywin32` to connect to the running SAP GUI process (login is handled automatically)
- QBI crawler uses Playwright (headless Chromium) — no SAP GUI required, but needs network access to `qbi.superhi-tech.com`
- SAP date format is `YYYY.MM.DD` (not DD.MM.YYYY)
- Process-specific SAP flows live in `libs/sap-gui/src/sap_gui/processes/<name>/`; projects are thin CLI wrappers
- Process data files (e.g., cost center lists) live alongside their process module, not in the project
- Use `pathlib.Path` for all file path parameters and return types
- Environment/config loading is the responsibility of the project entry point, not shared libs
- New libs go in `libs/`, new automations go in `projects/`

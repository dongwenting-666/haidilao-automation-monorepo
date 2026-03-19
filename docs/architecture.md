# Architecture Overview

## Monorepo Structure

```
haidilao-automation-monorepo/
├── libs/                          # Shared libraries
│   ├── sap-gui/                     # SAP GUI automation (cross-platform)
│   ├── qbi-crawler/                 # Quick BI web crawler (Playwright)
│   ├── excel-utils/                 # Shared Excel generation utilities
│   ├── vpn/                          # SealSuite VPN automation (cross-platform)
│   ├── ollama-client/               # LLM client wrapper
│   ├── lark-client/                 # Feishu/Lark bot client (messaging, Drive)
│   └── db-client/                   # PostgreSQL client (psycopg3 pool, migrations)
├── projects/                      # Automation projects
│   ├── ksb1-accounting-check/       # KSB1 month-over-month accounting check (CLI)
│   ├── ksb1-accounting-check-gui/   # Desktop GUI + PyInstaller EXE
│   └── daily-store-operation-report/ # Daily store operations Excel report
├── docker/                        # Docker Compose for PostgreSQL (port 5432)
├── server/                        # FastAPI HTTP server (LaunchAgent: com.haidilao.server, port 8000)
│   ├── src/server/                  # App, routes, scheduler, commands
│   └── tests/
├── docs/                          # Documentation
├── output/                        # Default export destination (gitignored)
│   ├── ksb1/                        # KSB1 accounting check exports
│   ├── qbi/                         # Quick BI dashboard exports
│   └── daily-report/                # Daily store operation report exports
├── .env                           # Environment variables (gitignored)
└── pyproject.toml                 # uv workspace root
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python >= 3.13 |
| Package Manager | [uv](https://docs.astral.sh/uv/) with workspaces |
| Build Backend | hatchling |
| SAP Integration | Windows: COM/ActiveX via pywin32; macOS: Scripting Console bridge (AppleScript + Nashorn JS) |
| Web Crawling | Playwright (headless Chromium) |
| Report Output | openpyxl (XLSX) |
| LLM Enhancement | Ollama (local, optional) |
| Desktop GUI | tkinter |
| EXE Packaging | PyInstaller (single-file) |
| Database | PostgreSQL 16 (Docker or external) |
| Messaging | Feishu/Lark bot API |
| Auth | Lark OAuth + itsdangerous cookie sessions |

## Package Relationships

```
projects/ksb1-accounting-check
    ├── depends on → libs/sap-gui        (SAP download)
    ├── depends on → libs/ollama-client   (optional LLM enhancement)
    ├── depends on → openpyxl            (report generation)
    └── depends on → python-dotenv       (env config)

projects/ksb1-accounting-check-gui
    ├── depends on → projects/ksb1-accounting-check  (core analysis)
    ├── depends on → libs/sap-gui                    (SAP download)
    ├── depends on → libs/ollama-client               (optional LLM)
    └── depends on → python-dotenv                   (.env loading)

projects/daily-store-operation-report
    ├── depends on → libs/qbi-crawler      (QBI data download)
    ├── depends on → libs/excel-utils      (workbook creation, data loading)
    ├── depends on → openpyxl             (direct styling, merged cells)
    └── depends on → python-dotenv        (env config)

libs/qbi-crawler
    └── depends on → playwright         (browser automation)

libs/excel-utils
    └── depends on → openpyxl           (Excel read/write)

server/
    ├── depends on → libs/vpn                         (VPN connect before runs)
    ├── depends on → libs/lark-client                 (run completion notifications)
    ├── depends on → libs/db-client                   (targets, competitors, admin users)
    ├── depends on → projects/ksb1-accounting-check   (report generation)
    ├── depends on → projects/daily-store-operation-report (report generation)
    └── depends on → fastapi / uvicorn                (HTTP server)

libs/lark-client
    └── depends on → httpx                            (HTTP client)

libs/db-client
    └── depends on → psycopg[binary], psycopg-pool    (PostgreSQL driver)
```

Dependencies between workspace packages are declared via `[tool.uv.sources]` in each project's `pyproject.toml` using `workspace = true`.

## Package Layout Convention

All packages use Python src-layout:

```
<package>/
├── src/<package_name>/
│   ├── __init__.py
│   └── ...
├── tests/
│   └── test_*.py
└── pyproject.toml
```

## Design Principles

1. **Libs vs Projects** — Reusable automation logic lives in `libs/`. Projects are thin CLI/GUI entry points that compose library functionality.
2. **Process modules** — SAP transaction-specific flows (e.g., KSB1) live in `libs/sap-gui/src/sap_gui/processes/<name>/`, keeping the core library generic.
3. **Data files with code** — Process-specific data (cost center lists, mapping files) live alongside their process module, not in the project.
4. **Environment at the edge** — Only project entry points load `.env` and resolve credentials. Libraries accept parameters; env vars are only used for optional overrides (e.g., `SAP_CONNECTION`, `SAPGUI_APP`).
5. **pathlib everywhere** — All file path parameters and return types use `pathlib.Path`.
6. **Hybrid analysis** — Deterministic rules detect anomalies; optional LLM explains *why* they exist. Rules always run, LLM is opt-in.

## Data Flow: KSB1 Accounting Check

```
SAP GUI ──COM (Win) / Scripting Console (macOS)──> sap-gui library
    │
    ├── [macOS] Auto-launch SAP GUI if not running (auto_launch=True)
    ├── Login (auto)
    ├── Navigate to KSB1
    ├── Upload cost centers
    ├── Set date range (prev month + curr month)
    ├── Execute report
    └── Export to XLSX
            │
            ▼
    Raw KSB1 export (output/<year-month>/ksb1-<year-month>.XLSX)
            │
            ▼
    ksb1-accounting-check project
    │
    ├── Load mapping (报表科目.xlsx)
    ├── Enrich rows (add 月份, 科目)
    ├── Split by month
    ├── For each store:
    │   ├── Build 科目 summary with 成本要素名称 detail
    │   ├── Run deterministic rules (rules.py)
    │   ├── [Optional] Enhance findings with LLM (llm.py)
    │   └── Write findings + detail rows to sheet
    ├── Write raw data sheet
    └── Write mapping reference sheet
            │
            ▼
    Report (output/<year-month>/<year-month>_KSB1_检查报告_<time>.XLSX)
```

### GUI Flow

```
User launches KSB1会计检查.exe
    │
    ├── Enter SAP credentials (or auto-loaded from .env)
    ├── Select month/year, output directory
    ├── [Optional] Select LLM model
    ├── Click "下载 SAP 数据 + 生成报告" or "仅生成报告"
    │
    ├── Background thread runs worker
    │   ├── SAP download (if applicable)
    │   └── Report generation
    │
    ├── Log output streams to GUI in real-time
    └── Success: offer to open output folder
```

## Data Flow: Daily Store Operation Report

```
Quick BI (qbi.superhi-tech.com) ──Playwright──> qbi-crawler library
    │
    ├── Login (LDAP)
    ├── Download 5 reports (3 daily + 2 time-period)
    │   ├── Current month MTD
    │   ├── Previous month same period
    │   ├── Previous year same period
    │   ├── Current month time slots
    │   └── Previous year time slots
    └── All from 不含税 sheet
            │
            ▼
    DownloadedFiles (5 XLSX paths)
            │
            ▼
    PostgreSQL (store_targets, store_competitors)
            │
            ▼ (via server.db)
    transform.py
    │
    ├── _load_all_raw_data() → RawData (26 typed fields)
    ├── _build_store_metrics() × 8 stores → StoreMetrics
    └── load_targets() from DB  [was: targets.json]
            │
            ▼
    ReportData (dates + 8 StoreMetrics)
            │
            ▼
    5 sheet builders:
    ├── comparison_sheet (shared) → Sheet 1: MoM (gold)
    ├── comparison_sheet (shared) → Sheet 3: YoY (blue)
    ├── yoy_summary → Sheet 2: region summary (gold)
    ├── time_period → Sheet 4: per-store time slots
    └── competitor → Sheet 5: 假想敌翻台率对比 (competitor data from DB)
            │
            ▼
    _format_numbers() → round floats, apply "0.00"
            │
            ▼
    database_report_YYYY_MM_DD.xlsx (output/daily-report/)
            │
            ▼
    server.notify.notify_run_complete() → Lark card message (if configured)
```

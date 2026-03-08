# Architecture Overview

## Monorepo Structure

```
haidilao-automation-monorepo/
├── libs/                          # Shared libraries
│   ├── sap-gui/                     # SAP GUI COM automation
│   └── ollama-client/               # LLM client (reserved for future use)
├── projects/                      # Automation projects (thin CLI wrappers)
│   └── ksb1-accounting-check/       # KSB1 month-over-month accounting check
├── docs/                          # Documentation
├── output/                        # Default export destination (gitignored)
├── .env                           # Environment variables (gitignored)
└── pyproject.toml                 # uv workspace root
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python >= 3.13 |
| Package Manager | [uv](https://docs.astral.sh/uv/) with workspaces |
| Build Backend | hatchling |
| SAP Integration | COM/ActiveX via pywin32 |
| Report Output | openpyxl (XLSX) |

## Package Relationships

```
projects/ksb1-accounting-check
    ├── depends on → libs/sap-gui        (SAP download)
    ├── depends on → libs/ollama-client   (future LLM use)
    ├── depends on → openpyxl            (report generation)
    └── depends on → python-dotenv       (env config)
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

1. **Libs vs Projects** — Reusable automation logic lives in `libs/`. Projects are thin CLI entry points that compose library functionality.
2. **Process modules** — SAP transaction-specific flows (e.g., KSB1) live in `libs/sap-gui/src/sap_gui/processes/<name>/`, keeping the core library generic.
3. **Data files with code** — Process-specific data (cost center lists, mapping files) live alongside their process module, not in the project.
4. **Environment at the edge** — Only project entry points load `.env` and resolve credentials. Libraries accept parameters, never read environment variables.
5. **pathlib everywhere** — All file path parameters and return types use `pathlib.Path`.

## Data Flow: KSB1 Accounting Check

```
SAP GUI (running) ──COM/ActiveX──> sap-gui library
    │
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
    │   └── Write findings + detail rows to sheet
    ├── Write raw data sheet
    └── Write mapping reference sheet
            │
            ▼
    Report (output/<year-month>/<year-month>_KSB1_检查报告_<time>.XLSX)
```

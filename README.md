# 海底捞兔子Agent加拿大片区管理后台

Monorepo for Haidilao Canada automation jobs, managed with [uv workspaces](https://docs.astral.sh/uv/concepts/workspaces/).

## Structure

```
├── libs/                        # Shared libraries
│   ├── db-client/                 # PostgreSQL database client
│   ├── excel-utils/               # Excel reading/writing helpers
│   ├── lark-client/               # Lark/Feishu API client
│   ├── ollama-client/             # Ollama LLM client
│   ├── qbi-crawler/               # Quick BI (QBI) Playwright automation
│   ├── sap-gui/                   # SAP GUI automation (COM/ActiveX)
│   │   └── processes/ksb1/        # KSB1 export process + cost centers
│   └── vpn/                       # CorpLink VPN management (connect/status)
├── projects/                    # Automation projects (thin CLI wrappers)
│   ├── daily-store-operation-report/  # Daily QBI store operations report
│   ├── ksb1-accounting-check/        # KSB1 month-over-month accounting check
│   ├── ksb1-accounting-check-gui/    # KSB1 check with GUI frontend
│   ├── store-hours-collect/          # Daily store working hours collection
│   └── treasury-loan-watch/          # Treasury loan maturity alerting
├── server/                      # FastAPI server (job runner + admin panel)
├── docker/                      # Docker / init scripts
├── scripts/                     # Utility scripts
├── tools/                       # Standalone tools
│   └── corplink-vpn-helper/       # CorpLink VPN gRPC helper (Go)
└── output/                      # Default export destination (gitignored)
```

## Prerequisites

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- CorpLink VPN connected (for QBI and SAP access)
- SAP GUI 770 (for KSB1 projects — Windows only)
- Playwright browsers installed (`uv run playwright install chromium`)

## Software Install Links

| Software | Link |
|----------|------|
| SAP GUI (macOS) | [Feishu Wiki — SAP GUI Mac 安装指南](https://haidilao.feishu.cn/wiki/DWcHwOsf0iLjvlkHeZncJpyhn0g) |
| SAP GUI (Windows) | [Feishu Doc — SAP GUI Windows 安装指南](https://haidilao.feishu.cn/docx/SWOkdCypPob5GOxOoXHcX8mvnO6) |
| SealSuite (飞连 VPN) | [Volcengine — 飞连下载](https://www.volcengine.com/product/feilian/download) |

## Setup

```bash
# Clone and install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env

# Install Playwright browsers
uv run playwright install chromium
```

## Server

The FastAPI server hosts all automation jobs and provides an admin panel.

```bash
# Start the server
uv run --project server python -m server

# Server runs on http://0.0.0.0:8000
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/reports/daily/{date}` | Trigger daily store operations report |
| `GET /api/runs` | List all job runs |
| `GET /api/runs/{run_id}` | Get run status and logs |
| `POST /api/github/webhook` | Receive GitHub issue/comment events (HMAC-verified) |

### Admin Panel

The admin panel is available at `/admin` and provides a web UI for managing and monitoring jobs.

## Projects

### Daily Store Operation Report

Downloads daily/time-period reports from Quick BI (QBI), computes store metrics, and generates an XLSX report. Automatically handles VPN reconnection (CorpLink has a 7.5h session timeout).

```bash
# Generate report for a specific date
uv run --project projects/daily-store-operation-report \
    python -m daily_store_operation_report.main 2026-03-17
```

### KSB1 Accounting Check

Downloads KSB1 (Cost Center: Actual Line Items) data from SAP, then generates a month-over-month comparison report per store using **deterministic rule-based analysis**. The output is an XLSX workbook with one sheet per store (findings + detail rows), a raw data sheet, and a mapping reference sheet.

Analysis highlights:
- Cost elements present in one month but missing in the other
- Significant amount differences (>500 CAD and >20% change)
- Key cost elements (rent, utilities, insurance, etc.) flagged at a lower threshold (>100 CAD)

```bash
# Check previous month (default)
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Check a specific month/year
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main 2 2026

# Skip SAP download, reuse existing KSB1 export
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --skip-download
```

### Store Hours Collect

Collects daily store working-hour data. Runs daily at 6:30 AM Vancouver time — checks for a monthly spreadsheet in the target folder (creates from template if missing), then populates the day's data.

### Treasury Loan Watch

Reads the treasury loan sheet from Feishu and sends a Lark notification for any loans maturing today.

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `SAP_USERNAME` | SAP login username |
| `SAP_PASSWORD` | SAP login password |
| `QBI_USERNAME` | Quick BI login username |
| `QBI_PASSWORD` | Quick BI login password |
| `DATABASE_URL` | PostgreSQL connection string |
| `LARK_APP_ID` | Lark/Feishu app ID |
| `LARK_APP_SECRET` | Lark/Feishu app secret |

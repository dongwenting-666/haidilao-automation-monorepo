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
├── docker/                      # Docker / init scripts + docker-compose
├── scripts/                     # Utility scripts
├── tools/                       # Standalone tools
│   └── corplink-vpn-helper/       # CorpLink VPN gRPC helper (Go)
└── output/                      # Default export destination (gitignored)
```

## Prerequisites

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- Docker (for PostgreSQL, MinIO)
- CorpLink VPN connected (for QBI and SAP access)
- SAP GUI 770 (for KSB1 projects — Windows only)
- Playwright browsers (`uv run playwright install chromium`)

## Setup

```bash
# Clone and install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env

# Start PostgreSQL + MinIO (Docker)
docker compose -f docker/docker-compose.yml up -d

# Install Playwright browsers
uv run playwright install chromium
```

## Service Management

The server runs as a macOS LaunchAgent with `KeepAlive: true`.

```bash
# Start / stop / restart
launchctl start com.haidilao.server
launchctl stop com.haidilao.server
launchctl stop com.haidilao.server && launchctl start com.haidilao.server

# View logs
tail -f server.log

# Check status
curl http://localhost:8000/api/runs
```

> **⚠️ Important:** The LaunchAgent plist at `~/Library/LaunchAgents/com.haidilao.server.plist`
> sets its own `EnvironmentVariables`. When adding new env vars, update **both** `.env` and
> the plist, then restart via `launchctl`. The plist env vars take precedence over `.env`
> for values that `auth.py` reads via `os.environ`.

## Server

The FastAPI server hosts all automation jobs and provides an admin panel.

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/reports/daily/{date}` | Trigger daily store operations report |
| `GET /api/runs` | List all job runs |
| `GET /api/runs/{run_id}` | Get run status and logs |
| `POST /api/github/webhook` | GitHub issue/comment webhook (HMAC-SHA256 verified) |
| `GET /api/tools/agent/{key}` | Download file from MinIO (localhost-only, no auth) |

### Admin Panel (`/admin`)

Requires Lark OAuth login. Users must be in `ADMIN_WHITELIST`.

| Path | Description | Access |
|------|-------------|--------|
| `/admin/targets` | Monthly store revenue + turnover rate targets | All admins |
| `/admin/competitors` | Store → competitor benchmark mappings | All admins |
| `/admin/users` | User whitelist management | All admins |
| `/admin/tools` | File upload/download (MinIO) | Super admins only |

### GitHub Integration

Issues and feature requests are tracked via [GitHub Issues](https://github.com/HongmingWang-Rabbit/haidilao-automation-monorepo/issues). An agent cron checks every 2 minutes for new issues/comments via webhook triggers.

**Workflow labels:** `agent:triage` → `agent:planning` → `agent:approved` → `agent:in-progress` → `agent:done`

## Projects

### Daily Store Operation Report

Downloads daily/time-period reports from Quick BI (QBI), computes store metrics, and generates an XLSX report. Automatically handles VPN reconnection (CorpLink has a 7.5h session timeout).

```bash
uv run --project projects/daily-store-operation-report \
    python -m daily_store_operation_report.main 2026-03-17
```

### KSB1 Accounting Check

Downloads KSB1 data from SAP, generates month-over-month comparison report per store using rule-based analysis. Flags missing cost elements, significant amount changes, and key cost element anomalies.

```bash
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main 2 2026
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --skip-download
```

### Store Hours Collect

Daily at 6:30 AM — collects store working-hour data into monthly Feishu spreadsheets.

### Treasury Loan Watch

Reads treasury loan sheet from Feishu, sends Lark alert for loans maturing today.

## Environment Variables

See `.env.example` for the full list with descriptions.

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `SESSION_SECRET` | HMAC key for signing admin session cookies |
| `ADMIN_WHITELIST` | Comma-separated Lark open_ids for admin access |
| `SUPER_ADMIN_OPEN_IDS` | Comma-separated Lark open_ids for super admin (Tools) |
| `LARK_APP_ID` / `LARK_APP_SECRET` | Lark/Feishu app credentials |
| `QBI_USERNAME` / `QBI_PASSWORD` | Quick BI login |
| `SAP_USERNAME` / `SAP_PASSWORD` | SAP login |
| `GITHUB_WEBHOOK_SECRET` | GitHub webhook HMAC secret |
| `MINIO_ENDPOINT` | MinIO server (default: `localhost:9000`) |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | MinIO credentials |

# CLAUDE.md — Project Conventions & Architecture Notes

## Architecture

- **Monorepo** managed by `uv workspaces` — libs/ for shared code, projects/ for CLI wrappers, server/ for the FastAPI app
- **Server** runs as a macOS LaunchAgent (`com.haidilao.server`) with `KeepAlive: true`
- **Reverse proxy**: nginx on the same host, proxies `haidilao.wanghongming.xyz` → `localhost:8000`
- **Storage**: PostgreSQL (Docker) + MinIO (Docker) for file uploads
- **Auth**: Lark OAuth → signed session cookies (itsdangerous `TimestampSigner`)

## Key File Paths

| File | Purpose |
|------|---------|
| `server/src/server/app.py` | FastAPI app, router registration, exception handlers |
| `server/src/server/auth.py` | Session signing, whitelist, super admin checks |
| `server/src/server/config.py` | Pydantic `Settings` — loads `.env` |
| `server/src/server/db.py` | DB access layer (targets, competitors, admin users, travel budget) |
| `server/src/server/routes/admin.py` | Admin UI — all admin pages (targets, reports, message log, etc.) |
| `server/src/server/routes/tools.py` | MinIO file upload/download + admin UI |
| `server/src/server/routes/github_webhook.py` | GitHub webhook receiver |
| `server/src/server/notify.py` | Lark notifications — cards, file delivery, screenshots |
| `server/src/server/routes/runs.py` | Run queue, execution, post-run notification hooks |
| `server/src/server/sheet_screenshot.py` | Render Excel sheets to PNG for Lark delivery |
| `server/notify.toml` | Lark chat ID aliases (`[chats]`) + per-command notification targets |
| `server/src/server/commands/` | Command definitions: daily-report, ksb1, travel-expense-budget, f13-clearing, store-hours-collect, treasury-loan-watch |
| `libs/lark-client/` | Lark API client (send_text, send_card, send_file, send_image) |
| `libs/qbi-crawler/` | QBI report download via Playwright |
| `libs/sap-gui/` | SAP GUI automation (KSB1, F.13) via AppleScript/COM |
| `libs/vpn/` | CorpLink VPN automation via cliclick |
| `projects/daily-store-operation-report/` | Daily store operation report (5-sheet Excel from QBI data) |
| `projects/ksb1-accounting-check/` | KSB1 accounting check (SAP cost center comparison) |
| `projects/travel-expense-budget/` | Travel expense budget report (差旅费预算明细) |
| `scripts/server-start.sh` | Server launcher with crash alerting |
| `scripts/lark-notify.py` | CLI: send Lark message by alias |
| `~/Library/LaunchAgents/com.haidilao.server.plist` | LaunchAgent config |
| `/opt/homebrew/etc/nginx/sites-enabled/haidilao.conf` | Nginx reverse proxy config |

## Admin Pages

| Page | URL | Description |
|------|-----|-------------|
| 月度目标 | `/admin/targets` | Per-store monthly targets (revenue, turnover rate) |
| 假想敌配置 | `/admin/competitors` | Competitor store mapping |
| 差旅预算 | `/admin/travel-budget` | Travel budget targets (revenue, travel, Q1, exchange rate) |
| 自动化报表 | `/admin/reports` | Reports hub — links to all report triggers |
| 每日经营日报 | `/admin/daily-report` | Daily report manual trigger (date picker, skip-download) |
| KSB1核查 | `/admin/ksb1` | KSB1 accounting check trigger |
| 差旅费预算 | `/admin/travel-expense-budget` | Travel expense budget report trigger |
| 消息记录 | `/admin/message-log` | Bot message viewer + recall per chat group |
| 工具 | `/admin/tools` | File upload (MinIO) — super admin only |
| API密钥 | `/admin/api-keys` | API key management — super admin only |

## Registered Commands

| Command | Project | Schedule | Description |
|---------|---------|----------|-------------|
| `daily-report` | `daily-store-operation-report` | Daily 6:00 AM Vancouver | QBI→5-sheet Excel→Lark (production group + finance screenshots) |
| `ksb1` | `ksb1-accounting-check` | On-demand | SAP KSB1→month-over-month comparison→Lark @mention |
| `travel-expense-budget` | `travel-expense-budget` | On-demand | KSB1 travel data + DB targets→budget report→Lark |
| `f13-clearing` | (server command) | Monthly 10th 7:00 AM | SAP F.13 automatic clearing→Lark status |
| `store-hours-collect` | (server command) | Daily 6:30 AM | Daily report→Feishu sheet auto-fill→Lark alerts |
| `treasury-loan-watch` | `treasury-loan-watch` | Daily 6:00 AM | Feishu sheet→loan maturity check→Lark alert |

## Critical Lessons Learned

### 1. Always read config from `settings`, never `os.environ`
`pydantic-settings` loads `.env` into the `Settings` object but does **NOT** populate `os.environ`. All server code must read from `settings` — never use `os.environ.get()` directly.

**Rule:** Add new config to `Settings` in `config.py`, then read via `settings.field_name`. Example:
```python
from server.config import settings
value = settings.some_field  # loaded from .env by pydantic-settings
```

### 2. `.env` is the single source of truth for secrets
All server config reads from pydantic `Settings` which loads `.env`. The plist only has `HOME`, `PATH`, `LARK_APP_ID`, `LARK_APP_SECRET` (needed by the crash-alert script before dotenv runs).

When adding new env vars: add to `.env` only. Add to the plist **only** if the crash-alert script in `server-start.sh` needs it before the Python server starts.

### 3. CorpLink VPN
- 450-minute (7.5h) max session timeout — auto-disconnects
- `cliclick` works on Electron apps; `CGEvent` does not (without proper CGEventSource)
- CorpLink gRPC is cert-locked — only ByteDance-signed processes can call it

### 4. QBI Export Flakiness
The Quick BI export dialog occasionally fails to render. `_click_export_and_wait_for_dialog()` retries up to 3 times with stale modal dismissal between attempts.

### 5. Nginx Upload Temp Dir
Nginx workers run as `nobody`. The `client_body_temp` directory must be writable. On macOS with Homebrew nginx, the default path under `/opt/homebrew/var/run/nginx/` can have permission issues. Fixed by setting `client_body_temp_path /tmp/nginx_client_body_temp` in the server block.

### 6. QBI T-2 Data Reliability
QBI data for a given date is only finalized and reliable **two days later (T-2)**. Data for T-1 or today (T) may be incomplete or still updating. The daily report enforces this:
- `main.py` computes `vancouver_today` with `ZoneInfo("America/Vancouver")` — this is the reference clock
- Default date is `vancouver_today - timedelta(days=2)` (T-2)
- Any explicitly passed date more recent than T-2 is rejected with a Lark alert and `sys.exit(1)`
- The scheduler's `CronTrigger` must include `timezone="America/Vancouver"` so the 6 AM cron fires at 6 AM Vancouver time, not 6 AM UTC

There is no `--force` flag to bypass T-2. If you need to generate a report for a more recent date for testing, temporarily change the date constraint in `main.py` (and revert before committing).

### 7. Weighted vs Simple Average for Region Turnover Rate

**Comparison sheets (对比上月表 / 对比上年表):** The region-level cumulative monthly turnover rate is a **seat-weighted average** — NOT a simple mean:

```
region_avg_tr = total_assessed_tables_MTD / (total_seats × days_elapsed_in_month)
```

- `total_assessed_tables_MTD`: sum of `mtd_tables` across all stores
- `total_seats`: sum of `seats` across all stores (skipping stores with 0 seats)
- `days_elapsed_in_month`: `dates.day_of_month` (1 on the 1st, 31 on the 31st)

This matches QBI's "当月累计平均翻台率" calculation.

**Time-period sheet (分时段-上报) region row:** Three categories of columns, applied per column:
- **Seat-weighted avg** (cols 3=今年TR, 5=本月目标, 8=当日TR): `Σ(val × seats) / Σ(seats)` for stores with seats > 0
- **Simple avg excluding zeros** (cols 4=去年TR, 10=去年同周同日TR): `Σ(val) / count(nonzero)` — zero-excluded because prior-year stores may not exist
- **Sum** (桌数 cols 9, 11, 13, 14, 15): straight sum across stores
- **Derived** (cols 6=目标差异, 7=同比差异, 12=翻台率同比差異): computed **after** the averaging loop as `col3 - col5`, `col3 - col4`, `col8 - col10` — NOT averaged directly. Averaging differences independently gives a different (wrong) result than computing the difference of averaged values.

General rule: **difference = f(avg, avg), not avg(difference)**.

### 8. QBI File Session Management (Multiple Downloads in Same Dir)

When running with `--skip-download`, the resolver (`_resolve_data_files`) sorts QBI files by the timestamp embedded in their filename (e.g. `20260319_2001`). If multiple download sessions have files in the same `output/qbi/` directory, it takes the **3 most-recent daily files** and **2 most-recent time-period files**. This is fragile when sessions differ by only a few minutes or when there are stale leftover files.

**Safe pattern — use explicit file flags instead of `--skip-download` + directory:**
```bash
uv run --project projects/daily-store-operation-report \
    python -m daily_store_operation_report.main 2026-03-17 \
    --cur-daily output/qbi/海外门店经营日报数据_20260319_2001.xlsx \
    --prev-daily output/qbi/海外门店经营日报数据_20260319_2002.xlsx \
    --yoy-daily output/qbi/海外门店经营日报数据_20260319_2003.xlsx \
    --cur-tp output/qbi/海外分时段报表_20260319_2001.xlsx \
    --yoy-tp output/qbi/海外分时段报表_20260319_2002.xlsx
```

All 5 explicit flags are required together (the parser enforces this). The timestamp-consistency check (`validate_file_timestamps`) warns if the resolved files span more than 15 minutes — a sign of cross-session mixing. The all-zero validation in stage 3 (`validate_no_all_zero_columns`) is the catch-all if the wrong files are used.

### 9. Multi-stage Validation Pipeline
`validation.py` runs checks at 4 stages:
1. **File-level** (`validate_file_exists_and_readable`, `validate_xlsx_has_sheet`, `validate_file_timestamps`): runs before any processing
2. **Row-level** (`validate_daily_rows`, `validate_time_period_rows`): runs after loading each xlsx sheet
3. **Transform-level** (`validate_store_coverage`, `validate_no_all_zero_columns`): runs after computing metrics — `validate_no_all_zero_columns` raises a `ValueError` if ALL stores have zero MTD revenue (hard error; signals a file-ordering bug like the one fixed in 5274ed0)
4. **Post-generation** (`validate_report_output`): opens the saved xlsx and checks key cells; soft failure (logs warning, doesn't abort)

The all-zero check in stage 3 is what catches the file-sort bug: if `cur_daily`, `prev_daily`, and `yoy_daily` are in the wrong order, the YoY rows get filtered out and appear as all-zero.

### 10. Module-level `os.environ` reads are frozen at import time
If a module does `SECRET = os.environ.get("SOME_SECRET", "")` at the top level, the
value is captured once when Python imports the module — before launchd env vars are
necessarily visible. Always read env vars lazily (inside a function) or via `settings`.
Example: `github_webhook.py` used to have `WEBHOOK_SECRET = os.environ.get(...)` at
module level; it now calls `_get_webhook_secret()` at request time.

### 11. `uv` Build Caching
`uv run --project server` caches the editable install. After changing server code, run `uv sync --project server --reinstall-package server` or the old code may still be loaded. The LaunchAgent restart handles this automatically since it does a fresh `uv run`.

## Server Restart Procedure

```bash
# Correct way (uses launchd):
launchctl stop com.haidilao.server && launchctl start com.haidilao.server

# Wrong way (launchd will restart the old process):
kill $(pgrep -f 'python -m server')  # DON'T — launchd KeepAlive respawns it
```

### 12. Known Noise: `PythonFinalizationError` in Run Logs

Every `daily-report` subprocess run ends with a harmless traceback:

```
Exception ignored while calling deallocator <function ConnectionPool.__del__ ...>:
PythonFinalizationError: cannot join thread at interpreter shutdown
```

This is a known `psycopg-pool` / Python 3.14 incompatibility: the pool's `__del__` tries to join a thread during interpreter shutdown, which Python 3.14 disallows. It does **not** affect run results — runs show `status: success` and the report file is saved correctly. No action needed unless psycopg-pool releases a fix.

### 13. Test File Naming — Avoid Duplicate Basenames

Without `__init__.py` in test directories, pytest (in default `prepend` import mode) identifies test
modules by their bare filename. Two test files with the same basename in different packages will
collide. Example: `libs/vpn/tests/test_e2e.py` and `server/tests/test_e2e.py` both resolve to the
module name `test_e2e`, causing pytest to abort collection.

**Fix applied:** `server/tests/test_e2e.py` was renamed to `server/tests/test_server_e2e.py`.

**Rule:** Use unique basenames for test files across the whole monorepo. Prefix with the package
name when the generic name (e.g. `test_e2e.py`) would otherwise collide:
- `test_vpn_e2e.py`, `test_server_e2e.py`, `test_ksb1_e2e.py` — unambiguous
- `test_e2e.py` — only safe if it exists in exactly one `tests/` directory

### 14. Lark Chat IDs are Named Aliases — Never Hardcode `oc_xxx`

All Lark group chat IDs live in **`server/notify.toml [chats]`** as named aliases. Never put a raw `oc_xxx` string in Python — this includes **docstrings and comments**.

```python
# ✅ correct
from lark_client import chat_id_for
chat_id = chat_id_for("hongming")

# ❌ wrong (executable code)
chat_id = "oc_78f29489a577f10e36ebf989bccdcc83"

# ❌ also wrong (docstring example with real ID)
"""
[chats]
hongming = "oc_78f29489a577f10e36ebf989bccdcc83"  # ← don't put this in a .py file
"""

# ✅ correct in docstrings (use placeholder)
"""
[chats]
hongming = "oc_..."   # see server/notify.toml for actual IDs
"""
```

Both `lark_client.notify_config._load_chats()` and `server.notify._load_config()` use `lru_cache(maxsize=1)`. **Changes to `notify.toml` require a server restart** — the cache is never hot-reloaded.

### 15. LaunchAgent Crash Alerting

The server is launched via `scripts/server-start.sh`, not `uv` directly. On any non-zero exit:
1. Sends a 🔴 Lark text alert to the `hongming` chat
2. Schedules an OpenClaw isolated agentTurn (`openclaw cron add --at 1m --session isolated`) so the agent wakes, investigates, and reports to Hongming on TUI

Clean exit (code 0, e.g. `launchctl stop`) = no alert. `KeepAlive.SuccessfulExit = false` means launchd only restarts on crash, not on clean shutdown. `ThrottleInterval = 30` prevents rapid crash loops.

### 17. Never call `launchctl start/stop/kickstart` from an agent cron

The OpenClaw agent crons (healthcheck, log-monitor) must **never** call `launchctl start`, `launchctl stop`, or `launchctl kickstart` on `com.haidilao.server`. launchd manages its own restart lifecycle — external `launchctl start` while launchd is already restarting the service causes a race condition that spawns dozens of competing uvicorn processes, all failing with `address already in use`.

**Safe auto-fix:** Docker containers only (`docker start <container>`).
**Everything else:** alert via Lark + report on TUI, let Hongming decide.

This lesson came from a restart storm on 2026-03-20 where the healthcheck cron triggered `launchctl start` during a launchd-managed recovery, spawning 50+ port-conflict failures in the log.

### 16. plist env vars — minimal set

The plist only contains: `HOME`, `PATH`, `LARK_APP_ID`, `LARK_APP_SECRET`. Everything else loads from `.env` via python-dotenv at server startup. `LARK_APP_ID`/`SECRET` must be in the plist because the crash-alert script in `server-start.sh` needs them *before* dotenv has run.

When adding a new secret: if the crash script (or any pre-server bootstrap) needs it, add it to **both** `.env` and the plist. Server-only secrets: `.env` only.

### 18. Two-Level Lark Notification Routing

Each scheduled command has **two independent notification layers**. They must be configured separately.

**Layer 1a — Run-complete card** (`notify.toml [command]` entry)
- `notify_run_complete(run)` in `server/notify.py` uses `_target_for(run.command)` from `notify.toml`
- Always routes to `hongming` for all commands — run cards are admin status, not business output

**Layer 1b — File/gate control** (`run.notify_chat` in `scheduler.py`)
- `create_run(..., notify_chat=<alias>)` in `scheduler.py` controls two things:
  1. Whether any server notification fires at all (empty = completely silent run)
  2. Where file delivery goes (daily-report xlsx → `run.notify_chat`)
- Rule: empty string = silent (for manual/test runs or agent-triggered runs)

**Layer 2 — Command-internal notifications** (inside the project's `main.py`)
- The command itself may send additional Lark messages based on its own logic
- `store-hours-collect` sends data-fill summaries to `store_hours` and unfilled alerts to `hongming`
- These are completely independent of Layer 1 — they always fire when the command runs

**Current routing table:**

| Command | notify.toml (run card) | run.notify_chat (file gate) | Internal (Layer 2) |
|---------|----------------------|----------------------------|--------------------|
| `daily-report` | `hongming` | `production_accounting_report_chat` (card+xlsx+screenshots) | `finance_study_group` (对比上年表+分时段 screenshots only) |
| `ksb1` | `hongming` | `production_accounting_report_chat` (xlsx+@mention) | — |
| `travel-expense-budget` | — | `hongming` (xlsx) | — |
| `f13-clearing` | `hongming` | — | — |
| `treasury-loan-watch` | `hongming` | `hongming` | `hongming` (loan alerts) |
| `store-hours-collect` | `hongming` (failure only) | `hongming` | `store_hours` (data summary) + `hongming` (unfilled alert, silent if ok) |

**Chat aliases** (defined in `server/notify.toml [chats]`):

| Alias | Chat ID | Purpose |
|-------|---------|---------|
| `hongming` | `oc_78f294...` | Server alerts, errors, admin reports |
| `production_accounting_report_chat` | `oc_ff2a74...` | Scheduled daily report xlsx + KSB1 reports |
| `finance_study_group` | `oc_d17d1a...` | Daily report screenshots (对比上年表 + 分时段) |
| `store_hours` | `oc_9fe9a8...` | Store hours data summaries |

**Rule:** never set `run.notify_chat` to `store_hours` or `production_accounting_report_chat` for anything other than their specific purpose. Those groups receive business outputs only — not server status cards.

## Agent / Subagent Rules

**Never run e2e tests unless explicitly asked.** SAP GUI e2e tests take over the screen.

- ✅ Safe: `uv run pytest server/tests/ libs/ projects/*/tests/ -q` — e2e excluded by default via `addopts = "-m 'not e2e'"` in root `pyproject.toml`
- ❌ Never: `pytest -m e2e`, running `libs/sap-gui/tests/e2e_ksb1.py`, or anything that invokes `sap_gui.processes`

### 19. Use LarkClient for All Lark API Calls — No Raw httpx

All Lark API calls must go through `LarkClient` from `libs/lark-client`. Never create
a raw `httpx` client, set `Authorization: Bearer ...` headers, or construct Lark API
URLs manually.

```python
# ✅ correct — use LarkClient._get for unlisted endpoints
with LarkClient(app_id=..., app_secret=...) as client:
    resp = client._get(f"/sheets/v2/spreadsheets/{token}/values/{range}")
    data = resp.json()

# ❌ wrong — bypasses token management, auth abstraction, and error handling
import httpx
resp = httpx.get(
    f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/...",
    headers={"Authorization": f"Bearer {raw_token}"},
)
```

`LarkClient._get`, `._post`, and `._put` handle token refresh, base URL assembly,
and `raise_for_status()`. For endpoints not covered by public methods (send_card,
send_text, etc.), use `client._post("/path", payload)` with a path relative to
`https://open.feishu.cn/open-apis`.

**Single client rule:** Open one `with LarkClient(...) as client:` block per function
and reuse it for all API calls (fetch + notify) — don't open a second client for
notifications.

### 20. Keep Tests in Sync When Refactoring Business Logic

When refactoring rules, thresholds, or business logic, always update the tests in the
same commit (or an immediate follow-up). Tests that test the **old** behavior will
silently pass false-positives only in isolation and fail in full suite runs, eroding
confidence in the test suite.

**Lesson from 9fcca5f / c627164:** `rules.py` was refactored to only report non-key
cost elements for NOTE_CURR_ONLY/NOTE_PREV_ONLY cases. The tests were not updated,
causing 5 failures. The fix required updating test assertions to match the new behaviour.

## Code Style

- Python 3.13+, type hints everywhere
- `from __future__ import annotations` in all modules
- Logging via `logging.getLogger(__name__)` — never `print()` in library/server code
- DB access through `server/db.py` helper functions, never raw SQL in routes
- HTML templates are inline f-strings in route files (no Jinja2)

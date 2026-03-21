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
| `server/src/server/db.py` | DB access layer (targets, competitors, admin users) |
| `server/src/server/routes/tools.py` | MinIO file upload/download + admin UI |
| `server/src/server/routes/github_webhook.py` | GitHub webhook receiver |
| `server/src/server/notify.py` | Lark notifications — run-complete cards, daily report file delivery |
| `server/src/server/routes/runs.py` | Run queue, execution, post-run notification + file send |
| `server/notify.toml` | Lark chat ID aliases (`[chats]`) + per-command notification targets |
| `libs/lark-client/src/lark_client/notify_config.py` | `chat_id_for(alias)` — resolves named chat aliases from notify.toml |
| `libs/qbi-crawler/src/qbi_crawler/dashboard.py` | QBI report navigation + export |
| `libs/vpn/src/vpn/_darwin.py` | CorpLink VPN reconnect via cliclick |
| `scripts/server-start.sh` | Server launcher with crash alerting (Lark + OpenClaw agent wake) |
| `scripts/lark-notify.py` | CLI: send Lark message by alias (`python scripts/lark-notify.py hongming "msg"`) |
| `~/Library/LaunchAgents/com.haidilao.server.plist` | LaunchAgent config (minimal env: HOME, PATH, LARK creds) |
| `/opt/homebrew/etc/nginx/sites-enabled/haidilao.conf` | Nginx reverse proxy config |

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

All Lark group chat IDs live in **`server/notify.toml [chats]`** as named aliases. Never put a raw `oc_xxx` string in Python.

```python
# ✅ correct
from lark_client import chat_id_for
chat_id = chat_id_for("hongming")

# ❌ wrong
chat_id = "oc_78f29489a577f10e36ebf989bccdcc83"
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

## Code Style

- Python 3.13+, type hints everywhere
- `from __future__ import annotations` in all modules
- Logging via `logging.getLogger(__name__)`
- DB access through `server/db.py` helper functions, never raw SQL in routes
- HTML templates are inline f-strings in route files (no Jinja2)

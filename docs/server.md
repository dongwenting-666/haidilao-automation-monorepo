# Server

FastAPI HTTP server that exposes automation results, triggers runs, and provides an admin web UI for managing store targets, competitors, and users.

**Production URL:** https://haidilao.wanghongming.xyz (proxied to `localhost:8000`)

---

## Architecture

| Component | Technology |
|-----------|-----------|
| HTTP framework | FastAPI + uvicorn |
| Background scheduler | APScheduler (cron) |
| Run queue | Python `asyncio.Queue` — serial execution (automations are not headless, must not overlap) |
| DB | PostgreSQL via `db-client` (optional — degrades gracefully) |
| Notifications | Lark bot via `lark-client` (optional) |
| Auth | Lark OAuth + signed cookie sessions |
| Session signing | `itsdangerous.TimestampSigner` |

**Serial queue:** All automation runs are queued and executed one at a time. A new run will show `pending` with a `queue_position` until the current run completes.

---

## LaunchAgent Setup

```bash
# The LaunchAgent plist lives at:
~/Library/LaunchAgents/com.haidilao.server.plist

# Manage with launchctl:
launchctl start  com.haidilao.server
launchctl stop   com.haidilao.server
launchctl list | grep haidilao  # check status

# Or restart by unloading/loading:
launchctl unload  ~/Library/LaunchAgents/com.haidilao.server.plist
launchctl load    ~/Library/LaunchAgents/com.haidilao.server.plist
```

The server runs as `uv run --project server python -m server` from the monorepo root. Logs go to `server.log` in the repo root.

---

## API Endpoints

### Runs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/runs` | List recent runs (up to 200) |
| `GET` | `/api/runs/{run_id}` | Get run status + logs |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/reports/daily/{date}` | Download daily report (YYYY-MM-DD); returns 200 (file) or 202 (queued) |
| `GET` | `/api/reports/daily/{date}/status` | Check status of a daily report run |
| `GET` | `/api/reports/ksb1/{year}/{month}` | Download KSB1 report; returns 200 (file) or 202 (queued) |
| `GET` | `/api/reports/ksb1/{year}/{month}/status` | Check status of a KSB1 report run |

### Files

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/files/` | List files in output directory (optionally `?subdir=path`) |
| `GET` | `/api/files/{path}` | Download a file from output directory (path-traversal safe) |

### Commands

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/commands` | List available automation commands |
| `POST` | `/api/commands/{name}/run` | Trigger a command run; body: `{"params": {...}}` |

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | List scheduled APScheduler jobs |

---

## Admin UI

All admin pages require authentication (Lark OAuth). Unauthenticated requests redirect to `/admin/login`.

| Path | Description |
|------|-------------|
| `/admin` | Redirects to `/admin/targets` |
| `/admin/login` | Lark OAuth login page |
| `/admin/oauth/callback` | OAuth callback (handled automatically) |
| `/admin/logout` | Clear session, redirect to login |
| `/admin/targets` | Manage monthly store targets (revenue + turnover rate per slot) |
| `/admin/competitors` | Manage store → competitor mappings |
| `/admin/users` | View Lark users who have logged in; toggle whitelist access |

### /admin/targets

Edit revenue targets (万 CAD) and turnover rate targets per time slot for each store and month. Month selector + inline save via JSON API (`POST /admin/targets`).

### /admin/competitors

Set the competitor store name for each of the 8 stores. Used to generate Sheet 5 (假想敌翻台率对比) in the daily report. Saved via `POST /admin/competitors`.

### /admin/users

Shows all `admin_users` rows (Lark open_id, name, first login time). Allows toggling `whitelisted` status per user via `POST /admin/users/whitelist`.

---

## Auth Flow

1. Unauthenticated request to any `/admin/*` page → redirect to `/admin/login?next=<path>`
2. Login page → redirects to Lark OAuth authorize URL
3. Lark callback with `?code=<code>` → server exchanges code for user info
4. `is_whitelisted(open_id)` checks:
   - DB: `admin_users.whitelisted = true`
   - Fallback: `ADMIN_WHITELIST` env var (comma-separated open_ids)
5. Session cookie set (HMAC-signed, 8h TTL, `httponly`, `samesite=strict`)
6. Cookies are `Secure` by default; set `COOKIE_SECURE=false` in `.env` for local dev over HTTP

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LARK_APP_ID` | `` | Lark bot application ID |
| `LARK_APP_SECRET` | `` | Lark bot application secret |
| `DATABASE_URL` | `` | PostgreSQL DSN |
| `ADMIN_WHITELIST` | `` | Comma-separated Lark open_ids allowed admin access |
| `SESSION_SECRET` | `` | HMAC key for session cookies (random key if unset — sessions don't survive restart) |
| `LARK_OAUTH_REDIRECT_URI` | `https://haidilao.wanghongming.xyz/admin/oauth/callback` | Must match URI registered in Lark app console |
| `COOKIE_SECURE` | `true` | Set to `false` for local HTTP dev |
| `QBI_USERNAME` | `` | Quick BI LDAP username |
| `QBI_PASSWORD` | `` | Quick BI LDAP password |
| `SAP_USERNAME` / `SAP_PASSWORD` | `` | SAP login credentials |

All variables loaded from `.env` in the repo root via `pydantic-settings`.

---

## DB Integration

The server uses `db-client` for storing:
- **Store targets** (`store_targets` table) — monthly revenue + turnover rate
- **Competitor config** (`store_competitors` table) — replaces `competitor.json`
- **Admin users** (`admin_users` table) — tracks Lark users + whitelist status

`DATABASE_URL` is optional. All DB calls degrade gracefully — the server logs a warning and continues without DB features if it can't connect.

Migrations run automatically at startup via `maybe_run_migrations()`.

---

## Scheduler

Default cron job: daily report at 06:00 (`daily_report_cron = "0 6 * * *"`, configurable in `.env`).

The report command checks for missing targets/competitor config via `_check_config()` before running. If config is missing, it sends a Lark alert and aborts.

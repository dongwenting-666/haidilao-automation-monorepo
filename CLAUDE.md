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
| `libs/qbi-crawler/src/qbi_crawler/dashboard.py` | QBI report navigation + export |
| `libs/vpn/src/vpn/_darwin.py` | CorpLink VPN reconnect via cliclick |
| `~/Library/LaunchAgents/com.haidilao.server.plist` | LaunchAgent config (env vars!) |
| `/opt/homebrew/etc/nginx/sites-enabled/haidilao.conf` | Nginx reverse proxy config |

## Critical Lessons Learned

### 1. `os.environ` vs pydantic-settings
`pydantic-settings` loads `.env` into the `Settings` object but does **NOT** populate `os.environ`. Any code that reads `os.environ.get("SOME_VAR")` won't see `.env` values unless they're also exported in the shell or set in the LaunchAgent plist.

**Rule:** Always read from `settings` first, fall back to `os.environ`. Example:
```python
from server.config import settings
value = settings.some_field or os.environ.get("SOME_FIELD", "")
```

### 2. LaunchAgent plist is the source of truth
The server runs via launchd, not via your shell. Environment variables must be in **both**:
- `.env` (for pydantic-settings in `config.py`)
- `~/Library/LaunchAgents/com.haidilao.server.plist` (for `os.environ` access)

When adding new env vars, update both. Restart with `launchctl stop/start`.

### 3. CorpLink VPN
- 450-minute (7.5h) max session timeout — auto-disconnects
- `cliclick` works on Electron apps; `CGEvent` does not (without proper CGEventSource)
- CorpLink gRPC is cert-locked — only ByteDance-signed processes can call it

### 4. QBI Export Flakiness
The Quick BI export dialog occasionally fails to render. `_click_export_and_wait_for_dialog()` retries up to 3 times with stale modal dismissal between attempts.

### 5. Nginx Upload Temp Dir
Nginx workers run as `nobody`. The `client_body_temp` directory must be writable. On macOS with Homebrew nginx, the default path under `/opt/homebrew/var/run/nginx/` can have permission issues. Fixed by setting `client_body_temp_path /tmp/nginx_client_body_temp` in the server block.

### 6. `uv` Build Caching
`uv run --project server` caches the editable install. After changing server code, run `uv sync --project server --reinstall-package server` or the old code may still be loaded. The LaunchAgent restart handles this automatically since it does a fresh `uv run`.

## Server Restart Procedure

```bash
# Correct way (uses launchd):
launchctl stop com.haidilao.server && launchctl start com.haidilao.server

# Wrong way (launchd will restart the old process):
kill $(pgrep -f 'python -m server')  # DON'T — launchd KeepAlive respawns it
```

## Code Style

- Python 3.13+, type hints everywhere
- `from __future__ import annotations` in all modules
- Logging via `logging.getLogger(__name__)`
- DB access through `server/db.py` helper functions, never raw SQL in routes
- HTML templates are inline f-strings in route files (no Jinja2)

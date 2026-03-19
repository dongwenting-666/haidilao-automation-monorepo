# Repo Maintenance Notes

## 2026-03-19 (Run 2) — Scheduled Maintenance

### Summary
Short pass — prior run (same day, earlier) had already cleaned up docs and .gitignore.
This run caught one leftover stale dependency from the reverted issue tracker.

### Fixes Applied

#### 1. Removed unused `grpcio` + `grpcio-tools` from `server/pyproject.toml` ✅
- These were added for the reverted issue tracker feature (`78def47`, reverted in `1e19f7d`)
- Zero grpc imports anywhere in `server/src/` — confirmed by grep
- Removing them shrank the lockfile by 83 lines
- **Commit:** `5efef4d`

#### 2. Added `POST /api/github/webhook` to README API endpoints table ✅
- The endpoint existed and was documented in `docs/server.md` and `CLAUDE.md` but was absent from README
- **Commit:** `5efef4d`

### No New Issues Found

- **README vs structure:** Matches.
- **CLAUDE.md / docs/:** Up to date from earlier run today.
- **output/daily-report/:** Reports present through 2026-03-17. **Mar 18 and Mar 19 are missing.**
  - Server logs confirm the 6 AM cron DID run (server was up, GitHub webhooks were flowing in both days)
  - Likely a VPN/QBI access failure or missing targets config — recommend checking `/api/runs` for the failed run IDs
- **grpcio audit:** No other packages had stale grpc imports.

### Recommendations

1. **Missing daily reports (Mar 18–19):** Check `/api/runs` at https://haidilao.wanghongming.xyz/api/runs for the failed run details. May need to trigger manually: `GET /api/reports/daily/2026-03-18` and `GET /api/reports/daily/2026-03-19`.
2. **`github_webhook.py` retention:** Still harmless (writes to /tmp, no DB dependency). If agent-admin collaboration isn't being revived, consider removing it in a future cleanup.

---

## 2026-03-19 (Run 1) — Scheduled Maintenance

### Summary
Routine maintenance pass. No structural changes needed — repo is in good shape.
Two doc gaps fixed, one .gitignore gap fixed.

### Findings

#### 1. Documentation Gaps Fixed ✅

**GitHub webhook undocumented:**
- `server/src/server/routes/github_webhook.py` was fully implemented and wired into `app.py`, but:
  - Not documented in `docs/server.md`
  - `GITHUB_WEBHOOK_SECRET` env var missing from `.env.example` and `CLAUDE.md`
- **Fixed:** Added webhook endpoint table to `docs/server.md`, added env var to both `.env.example` and `CLAUDE.md`.

#### 2. .gitignore Gap Fixed ✅

- `.pytest_cache/` directories existed in root, `libs/vpn/`, and `server/` but weren't explicitly gitignored.
- They weren't tracked by git (working correctly), but `.gitignore` didn't document this exclusion.
- **Fixed:** Added `.pytest_cache/` to `.gitignore`.

### No Issues Found (Run 1)

- **README vs structure:** README fully matches current structure.
- **CLAUDE.md:** Up to date; key file paths, conventions, all commands present.
- **docs/:** All projects/libs have corresponding doc files.
- **`__init__.py` files:** All packages have them.
- **pyproject.toml consistency:** All packages use hatchling, `requires-python = ">=3.13"`, `src/` layout.
- **Unused imports:** Spot-checked active files — all imports used.
- **Modularity:** Clean dependency graph; libs → no circular imports.

### Commits (Run 1)

| Hash | Message |
|------|---------|
| `da3a054` | docs: document GitHub webhook endpoint and add GITHUB_WEBHOOK_SECRET to .env.example |
| `f5f98b0` | chore: add .pytest_cache to .gitignore |

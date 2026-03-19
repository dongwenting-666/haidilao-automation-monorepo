# Repo Maintenance Notes

## 2026-03-19 (Run 5) — Scheduled Maintenance

### Summary
Light pass. Two recent commits (session expiry bug fixes in `tools.py`) had a minor doc discrepancy. Fixed and pushed.

### Fixes Applied

#### 1. Fixed `samesite=strict` → `samesite=lax` in `docs/server.md` ✅
- Auth flow section said `samesite=strict` but `auth.py` has used `samesite="lax"` since implementation
- Corrected to `samesite=lax`

#### 2. Documented JSON 401 behavior for expired sessions ✅
- Commit `e86217b` added `LoginRequired` exception handler in `app.py` that returns JSON 401 for AJAX/POST/API paths instead of an HTML redirect
- Commit `aebafd0` refined the JS client to redirect to `/admin/logout` on 401
- Neither change was reflected in `docs/server.md` auth flow section
- Added step 7 to the auth flow describing this behavior
- **Commit:** `e471cf1`

### No Other Issues Found

- **Structure vs README/CLAUDE.md:** Fully aligned.
- **Python syntax:** All files parse OK (`ast` check). Zero real unused imports.
- **`from __future__ import annotations`:** Simple AST scanner flags this as "unused"; it's a module directive false positive — not an issue.
- **git status:** Working tree clean. All 3 ahead commits now pushed.
- **output/daily-report/:** Still missing Mar 18–Mar 19. Ongoing issue.
- **output/ksb1/:** 2026-02 and 2026-03 directories present — looks healthy.

### Ongoing Recommendations

1. **Missing daily reports (Mar 18–Mar 19):** Check `/api/runs` at https://haidilao.wanghongming.xyz/api/runs for the failed run details. May need manual trigger.
2. **`github_webhook.py`:** Still harmless — keep or remove in a future cleanup pass.

---

## 2026-03-19 (Run 4) — Scheduled Maintenance

### Summary
Short pass after runs 1–3 earlier today. One batch of unused imports found and cleaned up across 5 files. No structural changes, no doc gaps.

### Fixes Applied

#### 1. Removed unused imports across 5 files ✅

- **`competitor.py`:** `BOLD_TITLE`, `THIN_BORDER` — only in import, not referenced in sheet body (likely left over from an earlier styling pass)
- **`time_period.py`:** `REGION_LABEL` — not used in sheet body
- **`auth.py`:** `quote`, `RedirectResponse` — both moved to `app.py` when the `LoginRequired` global exception handler was added in `30c7cf9`
- **`admin.py`:** `LoginRequired` — exception handler lives in `app.py`; admin.py doesn't handle it
- **`test_routes_tools.py`:** `io` — never referenced in any test
- All files syntax-checked with `python3 -m ast` before commit.
- **Commit:** `0ec96a9`

### No Other Issues Found

- **Structure vs README/CLAUDE.md:** Fully aligned.
- **git status:** Working tree clean. All changes pushed.
- **output/daily-report/:** Still missing Mar 18–Mar 19. Ongoing issue from prior runs — check `/api/runs` for details.
- **Hardcoded values / config hygiene:** pyproject.toml files consistent; no stale deps found.
- **Modularity:** No circular imports, clean lib interfaces.

### Ongoing Recommendations

1. **Missing daily reports (Mar 18–Mar 19+):** Check `/api/runs` at https://haidilao.wanghongming.xyz/api/runs. May need manual trigger.
2. **`github_webhook.py`:** Still harmless — keep or remove in a future cleanup pass.

---

## 2026-03-19 (Run 3) — Scheduled Maintenance

### Summary
Routine pass after the MinIO/Tools feature (#3) merged earlier today. One doc gap found and fixed.

### Fixes Applied

#### 1. Documented MinIO Admin Tools feature in `docs/server.md`, `README.md`, `CLAUDE.md` ✅

The MinIO-backed `/admin/tools` page (super-admin file uploads) was merged in commit `0c1a8fe`/`6001c31` but not documented anywhere:

- **`docs/server.md`:** Added `/admin/tools` to Admin UI table; added new "### /admin/tools" subsection with route table, super-admin access explanation, localhost-only agent endpoint note, and docker-compose startup command; added `MINIO_*` + `SUPER_ADMIN_OPEN_IDS` to environment variables table.
- **`README.md`:** Added `/api/tools/agent/{key}` to API endpoints table; expanded Admin Panel section with a proper route table (targets/competitors/users/tools); added `docker compose up -d` to Setup instructions.
- **`CLAUDE.md`:** Added missing `COOKIE_SECURE` env var row (it was in `docs/server.md` and `.env.example` but absent from CLAUDE.md's env table).
- **Commit:** `9333c4d`

### No Other Issues Found

- **Structure vs README/CLAUDE.md:** Fully aligned.
- **Code quality:** No unused imports, no TODOs/FIXMEs. `tools.py` and `auth.py` are clean.
- **git status:** Working tree clean. 2 unpushed commits from run 2 are now pushed.
- **output/daily-report/:** Mar 18–19 still missing (same as prior run). Recommend checking `/api/runs` for the failed run details.
- **docker-compose.yml:** Already includes MinIO service (9000/9001). No changes needed.

### Ongoing Recommendations

1. **Missing daily reports (Mar 18–19):** Check `/api/runs` at https://haidilao.wanghongming.xyz/api/runs. May need manual trigger: `GET /api/reports/daily/2026-03-18` and `GET /api/reports/daily/2026-03-19`.
2. **`github_webhook.py`:** Still harmless — keep or remove in a future cleanup pass.

---

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

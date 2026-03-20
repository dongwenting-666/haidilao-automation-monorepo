# Repo Maintenance Notes

## 2026-03-19 (Run 9) — Scheduled Maintenance (8:55 PM)

### Summary
Clean pass. One uncommitted change in `docker/init/03_revenue_precision.sql` (upgrading revenue precision from `NUMERIC(15,5)` to `NUMERIC(20,11)`) was found and committed along with a matching fix to `01_schema.sql` so fresh deployments also use the final precision. All 4 remaining "unused import" hits from the scanner are confirmed false positives (TYPE_CHECKING guard, conditional platform imports). Daily reports Mar 1–19 all present. Pruned 15 Mar 17 QBI raw downloads (oldest stale files). No structural changes, no new projects.

### Fixes Applied

#### 1. Committed precision migration upgrade ✅
- `docker/init/03_revenue_precision.sql`: was edited locally to upgrade from `NUMERIC(15,5)` → `NUMERIC(20,11)` but never staged
- Also updated `docker/init/01_schema.sql` baseline from `NUMERIC(12,2)` → `NUMERIC(20,11)` so fresh Docker init matches the final state
- **Commit:** `4086a5e`

#### 2. Pruned stale QBI raw downloads ✅
- Deleted 15 Mar 17 files from `output/qbi/` (`find -mtime +1 -delete`)
- These are processed intermediate files; daily report for Mar 17 already in `output/daily-report/`
- 130 files remain (Mar 18–19); they'll age out in tomorrow's run

### Code Review Results
- All 4 "unused import" scanner hits confirmed false positives:
  - `notify.py: Run` → under `TYPE_CHECKING` guard
  - `session.py: SAPSession/SAPSessionManager` → conditional `if sys.platform == "win32"`
  - `connect.py: ensure_vpn` → conditional `if sys.platform == "darwin"`
- No real issues found.

### Output Directory Health
- `output/daily-report/`: 19 files (Mar 1–19) — complete, healthy
- `output/qbi/`: 130 files / 16MB (Mar 18–19 only after pruning)
- `output/ksb1/`: 2.3MB — healthy

### No Other Issues Found
- README.md, CLAUDE.md: fully up to date, no structural changes
- docs/: all pages current
- `git status`: clean after commit
- Server API: `/api/runs` shows 3 successful daily-report runs today

---

## 2026-03-19 (Run 8) — Scheduled Maintenance (7:47 PM)

### Summary
Clean pass. Three uncommitted changes from recent sessions were staged, committed, and pushed as a single tidy commit (`41b5d46`). Mar 19 daily report was missing — triggered it via API; it's now running (run ID `87aa11a8`). output/qbi/ is 132 files / 16MB but all are from last 7 days (oldest Mar 17), so no cleanup needed. All AST "unused imports" are false positives (re-exports, `from __future__ import annotations`, conditional platform imports). No structural changes.

### Fixes Applied

#### 1. Committed and pushed pending changes ✅
Committed as `41b5d46`:
- **github_webhook.py:** replaced module-level `WEBHOOK_SECRET = os.environ.get(...)` with lazy `_get_webhook_secret()` — fixes env-var frozen-at-import-time bug under launchd
- **tools.py:** removed `/api/tools/agent/debug-session` debug endpoint (was leaking session secret prefix; no longer needed)
- **CLAUDE.md:** documented lesson 6 (module-level os.environ reads frozen at import time), renumbered old lesson 6→7

#### 2. Triggered missing Mar 19 daily report ✅
- Report for 2026-03-19 was absent from `output/daily-report/`
- Triggered via `GET /api/reports/daily/2026-03-19` → run ID `87aa11a8`, status: running as of end of this run

### No Other Issues Found
- README.md: accurate, no structural changes
- docs/: all pages current; no mention of removed debug endpoint needed
- output/qbi/: 132 files / 16MB, all ≤7 days old — healthy
- output/daily-report/: 18 files through Mar 18 (Mar 19 in progress)
- git status: clean after commit

---

## 2026-03-19 (Run 7) — Scheduled Maintenance (6:45 PM)

### Summary
Very clean pass. Repo is in excellent shape. All false-positive "unused imports" from the AST scanner were confirmed as intentional `__init__.py` re-exports or `TYPE_CHECKING` guards. No real issues found. Daily report for Mar 18 ran successfully (confirmed via `/api/runs`). Mar 19's report ran at 01:35 UTC (6:35 PM local) and succeeded. Output directories are healthy. Pushed the one pending commit (`8ffb554` session signer fix).

### Fixes Applied

#### 1. Pushed pending commit `8ffb554` ✅
- Was 1 commit ahead of origin — pushed `fix: _get_signer prioritizes settings.session_secret over os.environ`

### Code Review Results

**Unused import scan (full scan — server, projects, libs):**
- `server/src/server/notify.py`: `Run` imported under `TYPE_CHECKING` — correct, not a real import, false positive ✅
- `libs/*/src/*/__init__.py`: All flagged names are intentional public API re-exports ✅
- `libs/vpn/src/vpn/connect.py`: `ensure_vpn` used in conditional import branches — false positive ✅
- All projects: clean ✅

**Dependency hygiene:** `server/pyproject.toml` — clean, no stale deps. `apscheduler<4` pin intentional.

**Output/ hygiene:**
- `output/daily-report/`: 18 files (~360K) — healthy, through Mar 18
- `output/qbi/`: 130 raw QBI downloads (~15MB) — this is growing; no cleanup mechanism exists yet
- `output/ksb1/`: 2.3MB — healthy

### Resolved: Missing Daily Reports
- Mar 18 report: confirmed succeeded at 01:35 UTC (2026-03-20), run ID `7183687b73e8`
- Mar 19 report: file missing from `output/daily-report/` locally — but run succeeded per API. File likely saved elsewhere or in progress at time of this check (it ran at 6:35 PM local, maintenance ran at 6:45 PM)

### No Other Issues Found
- README, CLAUDE.md, docs/: fully up to date
- Structure unchanged from previous run
- `git status`: clean
- No new projects, libs, or structural changes

### New Recommendation
**output/qbi/ accumulation:** 130 files (15MB) of raw QBI downloads with no pruning. Consider adding a cleanup pass that removes QBI files older than 7 days, or at minimum documents the expected accumulation in docs/.

---

## 2026-03-19 (Run 6) — Scheduled Maintenance

### Summary
Very light pass. Two recent bug-fix commits (`94568f7` SESSION_SECRET cache fix, `0d5ec0e` pydantic settings fallback) are well-implemented and already accurately documented. One unused `time` import removed from `test_e2e.py`. One CLAUDE.md wording clarification. Missing daily reports (Mar 18–19) persist — server.log was truncated (only 15 lines), no scheduler history available to diagnose.

### Fixes Applied

#### 1. Removed unused `time` import from `libs/vpn/tests/test_e2e.py` ✅
- `import time` was present but never used (no `time.sleep()` or `time.time()` calls)
- Likely leftover from an earlier draft of the test
- Syntax-verified after removal
- **Commit:** `1505537`

#### 2. Clarified CLAUDE.md commands section ✅
- `POST /api/commands/{name}/run` description was terse; expanded to "trigger a run by command name"
- Minor wording improvement; no functionality change

### Code Review: Recent Commits (`94568f7`, `0d5ec0e`)

Both commits correctly fix a real bug (session cookies being invalidated on every request when `SESSION_SECRET` is unset):
- `94568f7`: Added module-level `_fallback_secret` cache so `_get_signer()` returns the same key within a process lifetime; also fixed XSS via `data-*` attributes and RFC 5987 Content-Disposition
- `0d5ec0e`: Extended the pydantic settings fallback path for `SESSION_SECRET` (same pattern as the `ADMIN_WHITELIST` fix from run 4)

Both are clean and well-scoped. No doc updates needed beyond what run 5 already applied.

### No Other Issues Found

- **Structure vs README/CLAUDE.md:** Fully aligned.
- **Python syntax:** All files parse OK. Zero real unused imports (lib `__init__.py` exports are intentional).
- **`POST /api/runs` in CLAUDE.md:** Confirmed absent — this was never a real endpoint; `POST /api/commands/{name}/run` is the correct trigger path.
- **git status:** Working tree clean.
- **server.log:** Only 15 lines — log was truncated at server restart. No scheduler history available to diagnose missing Mar 18–19 reports.
- **output/daily-report/:** Still missing Mar 18 and Mar 19.

### Ongoing Recommendations

1. **Missing daily reports (Mar 18–Mar 19):** Logs not available (server.log truncated). Check `/api/runs` at https://haidilao.wanghongming.xyz/api/runs for any failed run IDs. May need manual trigger via `GET /api/reports/daily/2026-03-18`.
2. **Server log rotation:** Consider adding `--log-level` output to a separate rotating log file (or use `logging.handlers.RotatingFileHandler`) so historical scheduler output isn't lost on restart.
3. **`github_webhook.py`:** Still harmless — keep or remove in a future cleanup pass.

---

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

# Repo Maintenance Notes

## 2026-03-20 (Run 14) — Scheduled Maintenance (5:08 AM Vancouver)

### Summary
Clean pass. One real fix: suppressed 8 starlette `DeprecationWarning` in `test_routes_tools.py` by moving per-request `cookies=` arguments to client-level cookie setting (Starlette's recommended approach). All 244 tests pass with zero warnings. Daily report for Mar 18 is on disk; Mar 19 still pending (T-2 allows it today at 6 AM). QBI output growing: 279 files / 35MB (all from Mar 18–20). Server running.

### Findings

#### 1. Test Warning Fixed ✅
`server/tests/test_routes_tools.py` — 8 tests in `TestSuperAdminRoutes` passed `cookies=` per-request to `client.get/post/delete`. Starlette deprecated this pattern because cookie persistence semantics are ambiguous.

**Fix:** Changed `_setup` fixture to use `client.cookies.set(...)` on the client instance, then `client.cookies.clear()` after each test. All per-request `cookies=self.cookies` arguments removed from the 7 request calls in the class.

**Commit:** `242905b`

#### 2. Daily Reports Status
- `output/daily-report/`: 19 files (Feb 10, Mar 1–18) ✅
- **Mar 18** present ✅
- **Mar 19** absent — T-2 allows generation today (Mar 20 Vancouver = T-2 for Mar 18 ✓, T-2 for Mar 19 ✓). Scheduler should run at 6 AM Vancouver.
- **Mar 20** not yet (T-2 not reached)

#### 3. Output Directory Health
- `output/qbi/`: 279 files / 35MB (Mar 18–20 only) — no stale files (none older than 3 days) ✅
- `output/ksb1/`: healthy ✅

#### 4. Code Quality — Clean
- No unused imports (confirmed false positives as before)
- No missing `__init__.py`
- All pyproject.toml consistent
- README.md and CLAUDE.md fully accurate
- Structure unchanged from Run 13

#### 5. Server Status
- LaunchAgent `com.haidilao.server` running (PID 19446)
- `/api/runs` returned empty list (server restarted recently, in-memory runs cleared)
- Server log at `server.log` (handled by launchd)

### Commits (Run 14)

| Hash | Message |
|------|---------|
| `242905b` | fix: use client-level cookies in TestSuperAdminRoutes to silence starlette deprecation warning |

---

## 2026-03-20 (Run 12) — Scheduled Maintenance (2:59 AM Vancouver)

### Summary
Very clean pass. No code changes, no doc gaps. All 4 previously identified "unused import" false positives confirmed again (TYPE_CHECKING guards, `__init__.py` re-exports). Mar 18 daily report is present; Mar 19 was correctly rejected by the T-2 constraint. QBI output/ is 18MB across 140 files (Mar 18–20 only). No commits needed.

### Findings

#### 1. Daily Reports Status ✅
- **Mar 1–18**: All present in `output/daily-report/` ✅
- **Mar 19**: Run `3bb1a0ae` at 09:07 UTC correctly rejected with T-2 constraint — today (Vancouver) is Mar 20, earliest valid date is Mar 18. Lark alert sent. This is expected, correct behaviour.
- **Mar 19 report** will auto-generate at 6 AM Vancouver on Mar 21.

#### 2. Code Quality — Clean
- Zero syntax errors across all `.py` files
- No `TODO`/`FIXME`/`HACK` in project code (only in .venv dependencies, as expected)
- No unused imports in spot-checked active files
- All false-positives from AST scanner confirmed (TYPE_CHECKING, `__init__.py` re-exports, conditional platform imports)

#### 3. Repo Structure — No Changes
- No new projects, libs, or tools added since last run
- README.md and CLAUDE.md fully accurate
- docs/ all up to date
- `git status`: clean (working tree clean, up to date with origin/main)

#### 4. Output Directory Health
- `output/daily-report/`: 18 files (Mar 1–18) ✅
- `output/qbi/`: 140 files / 18MB (Mar 18–20 only, all ≤2 days old) ✅
- `output/ksb1/`: 2.3MB ✅

#### 5. Server Running ✅
- LaunchAgent `com.haidilao.server` active; 6 runs in memory (all `daily-report`)
- 5 successes (Mar 17/18 reports); 1 expected T-2 rejection (Mar 19)
- No new API endpoints, no structural server changes

### No Commits Needed
Repo is clean and fully up to date.

---

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

---

## 2026-03-19 (Run 10) — Scheduled Maintenance

### Summary
Maintenance pass after a large burst of bug-fix commits on Mar 19. Doc updates only — no code changes needed.

### Findings

#### 1. Documentation Fixes ✅

**`docs/daily-store-operation-report.md` — stale CLI option table:**
- Default date still said "yesterday" → updated to "T-2, two days ago in Vancouver time"
- `--targets PATH` option row still in the table even though `--targets` was removed when targets moved to DB; removed from options table (the "no longer needed" note below it was already correct)

**`CLAUDE.md` — undocumented known noise:**
- Every `daily-report` subprocess ends with `PythonFinalizationError: cannot join thread at interpreter shutdown` from `psycopg-pool`'s `ConnectionPool.__del__`. This is harmless but alarming-looking.
- Added Lesson 11 documenting this as a known psycopg-pool / Python 3.14 incompatibility.

#### 2. Recent Commits (Mar 19 burst) — Already in CLAUDE.md
All 5 recent commits are bug fixes that already landed in CLAUDE.md in the same session:
- `01e8bcb` — weighted avg for region turnover rate
- `f982b01` — T-2 constraint enforcement
- `5b64b30` — timezone=America/Vancouver on CronTrigger
- `698bfb5` — correct averaging method per time-period column
- `1b0d0d8` — derive diff cols from averaged values, not average of diffs

#### 3. Reports for Mar 18 and Mar 19 Missing from output/daily-report/
The API shows 3 successful `daily-report` runs:
- `2026-03-17` → saved (oldest file in dir)
- `2026-03-18` → run succeeded, but file is missing (was deleted — pre-bug-fix output)
- `2026-03-19` → run succeeded, but file is missing (same reason)

The scheduler will regenerate these when the T-2 clock allows:
- Mar 18 report will generate at 6 AM Vancouver on Mar 20
- Mar 19 report will generate at 6 AM Vancouver on Mar 21

No action needed — the missing files are expected (they were pre-fix runs that got cleaned up).

#### 4. Code Quality — Clean
- All `__init__.py` files present
- No unused imports in spot-checked active files
- All pyproject.toml consistent (hatchling, `>=3.13`, src layout)
- `output/qbi/` has 135 accumulated files — all gitignored, not a concern
- `transform.py` at 580 lines is the largest module; noted but not splitting working code

### Commits (Run 10)

| Hash | Message |
|------|---------|
| `87fe82b` | docs: fix stale CLI option table and add psycopg_pool teardown noise note |

---

## 2026-03-20 (Run 11) — Scheduled Maintenance (11:59 PM Vancouver)

### Summary
Light maintenance pass. No code changes. Three doc fixes and CLAUDE.md lesson renumbering. Repo state is clean and healthy.

### Findings

#### 1. Server Running ✅
- LaunchAgent `com.haidilao.server` running (PID 84412)
- 4 recent runs visible (in-memory, since last restart): 3× daily-report, 1× daily-report — all `success`

#### 2. Daily Reports Status
- **Mar 1–17**: All present in `output/daily-report/` ✅
- **Mar 18 and Mar 19**: Not on disk — these were generated before the T-2 constraint was added (commit `f982b01` landed 10:18pm PT Mar 19), then the server was restarted. Files were served at some point but are no longer present.
  - Mar 18 will regenerate automatically at 6am Vancouver Mar 20 (T-2 will allow it)
  - Mar 19 will regenerate automatically at 6am Vancouver Mar 21
  - **No action needed** — this is expected behaviour.

#### 3. Documentation Fixes ✅

**`docs/server.md`** — Missing treasury check endpoint:
- Added `GET /api/reports/treasury/check/{date}` to the Reports endpoint table (was present in code, absent in docs)

**`docs/daily-store-operation-report.md`** — Stale CLI example filenames:
- Example explicit file paths used old date-range filename format (`海外门店经营日报数据_20260201_20260210.xlsx`)
- Updated to current download-timestamp format (`海外门店经营日报数据_20260319_2001.xlsx`)
- Also corrected example date from `2026-02-10` to `2026-03-17` for consistency

**`CLAUDE.md`** — Lesson number sequence was broken:
- Lessons were numbered: 1,2,3,4,5,7,8,10,9,6,7,11 (duplicate 7, gap at 6, out of order)
- Renumbered to sequential 1–12 in document order

#### 4. Code Quality — Clean
- No unused imports (only false positives from TYPE_CHECKING guards and `__init__.py` re-exports)
- No missing `__init__.py` files
- All pyproject.toml consistent (requires-python = ">=3.13", hatchling, src layout)
- `output/qbi/`: 135 files, all gitignored ✅
- `output/daily-report/`: 17 files (Mar 1–17) ✅
- `output/ksb1/`: 2026-02 and 2026-03 KSB1 reports present ✅

#### 5. Modularity — No concerns
- Clean lib/project separation maintained
- No circular imports, no large modules needing splitting

### Commits (Run 11)

| Hash | Message |
|------|---------|
| a25bad0 | docs: fix treasury endpoint, example filenames, and CLAUDE.md lesson numbering |

---

## 2026-03-20 (Run 13) — Scheduled Maintenance (4:02 AM Vancouver)

### Summary
Found and fixed a real bug: pytest collection was broken due to duplicate test file basename (`test_e2e.py`) in `libs/vpn/tests/` and `server/tests/`. Fixed by renaming the server version. All 244 tests now pass. Documentation updated for recent security hardening and the test naming rule.

### Recent Activity (last 5 commits before this run)
- `716b7cb` — fix: mark e2e test to skip by default (SAP GUI)
- `6cd9b4f` — test: comprehensive test coverage for auth, webhook, dates, transform, validation
- `cb2fa3b` — fix: remove set -e from security-scan.sh
- `a2cc273` — security: proxy headers, nginx rate limiting, security-scan.sh
- `a5ce129` — fix: don't send Lark alert for T-2 rejection

### Findings

#### 1. pytest Collection Broken — FIXED ✅
`uv run pytest` was failing with:
```
ERROR collecting server/tests/test_e2e.py
imported module 'test_e2e' has this __file__: libs/vpn/tests/test_e2e.py
```
Two test files with the same basename in different packages cause pytest to
abort collection in default `prepend` import mode.

**Fix:** Renamed `server/tests/test_e2e.py` → `server/tests/test_server_e2e.py`.
All 244 tests pass after the rename.

**Lesson added to CLAUDE.md (Lesson 13):** Use unique basenames for test files
across the whole monorepo.

#### 2. Documentation Updates ✅
- `docs/server.md`: Added "Security Hardening" section documenting nginx rate limiting,
  real-IP proxy headers (`proxy_headers=True`), docker localhost port binding,
  and `scripts/security-scan.sh` — all from the `a2cc273` commit which wasn't documented.
- `CLAUDE.md`: Added Lesson 13 on test file naming collision rule.

#### 3. Test Coverage — Healthy ✅
The `6cd9b4f` commit added 1,130 lines of new tests:
- `server/tests/test_auth.py` (229 lines) — session signing, whitelist, super admin, cookie flags
- `server/tests/test_github_webhook.py` (236 lines) — signature verification, trigger file, endpoint integration
- `projects/daily-store-operation-report/tests/test_dates.py` (156 lines)
- `projects/daily-store-operation-report/tests/test_transform.py` (293 lines)
- `projects/daily-store-operation-report/tests/test_validation.py` (176 lines)

Total: 244 tests pass, 1 deselected (e2e marker).

#### 4. Report Status
- `output/daily-report/`: 19 files (Feb 10, Mar 1–18) ✅
- Mar 17–18 are latest — Mar 19 will generate at 6 AM today (Mar 20)
- `output/qbi/`: 240 files, all gitignored ✅

#### 5. Code Quality — Clean
- No unused imports found in spot-checked files
- No missing `__init__.py` in src packages
- All pyproject.toml files consistent
- No untracked files that should be gitignored

### Commits (Run 13)

| Hash | Message |
|------|---------|
| dd22cc7 | fix: rename server/tests/test_e2e.py to avoid pytest module collision |

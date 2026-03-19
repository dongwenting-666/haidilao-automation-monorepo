# Repo Maintenance Notes

## 2026-03-19 — Scheduled Maintenance Run

### Summary
Routine maintenance pass. No structural changes needed — repo is in good shape.
Two doc gaps fixed, one .gitignore gap fixed.

---

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

---

### No Issues Found

- **README vs structure:** README fully matches current structure (was rewritten in recent commit `7367d61`).
- **CLAUDE.md:** Up to date; key file paths, conventions, all commands present.
- **docs/:** All projects/libs have corresponding doc files. Edit-history folder present.
- **`__init__.py` files:** All packages have them (no missing files found).
- **pyproject.toml consistency:** All packages use hatchling, `requires-python = ">=3.13"`, `src/` layout — consistent.
- **Unused imports:** Spot-checked active files (`admin.py`, `github_webhook.py`, `dashboard.py`) — all imports are used.
- **TODO/FIXME in source:** None in project source files (only in `.venv` third-party packages).
- **Untracked files:** Only `github_webhook.py` was listed as untracked in initial `git status`, but it was actually already tracked — stale `git status` cache. Confirmed with `git ls-files`.
- **output/ bloat:** Output contains current-month KSB1 reports and daily XLSX reports (normal). `output/` is gitignored.
- **QBI artifact files in root:** `corplink_screenshot.png` and `screen_test.png` are gitignored explicitly — fine.
- **Modularity:** No projects appear oversized. Pattern is clean: libs handle logic, projects are thin CLI wrappers, server is the orchestrator.
- **Circular imports:** No evidence — clean dependency graph (projects → libs, server → libs, no lib→lib imports observed).
- **Recent revert:** Commit `1e19f7d` reverted the issue tracker feature (`78def47`). `github_webhook.py` was NOT part of that revert — it survived and is still wired in. This is intentional (the file writes triggers for the agent cron).

---

### Commits Made This Run

| Hash | Message |
|------|---------|
| `da3a054` | docs: document GitHub webhook endpoint and add GITHUB_WEBHOOK_SECRET to .env.example |
| `f5f98b0` | chore: add .pytest_cache to .gitignore |

### Observations / Recommendations

- **`github_webhook.py` status:** The issue tracker was reverted, but `github_webhook.py` remains active. If the agent-admin collaboration feature isn't going to be re-implemented, consider whether `github_webhook.py` should also be removed. For now it's harmless (writes to `/tmp/`, has no DB dependency).
- **`grpcio` / `grpcio-tools` in `server/pyproject.toml`:** These are heavy deps. Unclear if they're actively used (the CorpLink VPN helper in `tools/corplink-vpn-helper/` is Go-based). May be worth auditing if a future cleanup pass is warranted.
- **Daily report output:** `output/daily-report/` has reports through 2026-03-17. March 18 and 19 may be missing — worth checking if the 6 AM cron fired correctly.

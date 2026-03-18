# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Detailed documentation lives in `docs/`. See [docs/README.md](docs/README.md) for the full index.

## Project Overview

Monorepo for Haidilao paperwork automations. Uses **uv workspaces** with Python >= 3.13 and **hatchling** as the build backend.

## Server

The `server/` directory contains a FastAPI app that exposes automation results via HTTP.

- **LaunchAgent**: `com.haidilao.server` (managed via `launchctl`)
- **Port**: 8000
- **Key endpoints**:
  - `GET /api/reports/daily/{date}` — daily store operation report
  - `GET /api/reports/ksb1/{year}/{month}` — KSB1 accounting check report
  - `GET /api/runs/{run_id}` — automation run status/result

## Repository Layout

- `libs/` — Shared libraries: `sap-gui`, `qbi-crawler`, `excel-utils`, `vpn`, `ollama-client`
- `projects/` — Automation projects: `ksb1-accounting-check`, `ksb1-accounting-check-gui`, `daily-store-operation-report`
- `scripts/` — Standalone utility scripts (e.g., `vpn_reconnect.py`)
- `output/` — Default export destination (gitignored): `output/ksb1/`, `output/qbi/`, `output/daily-report/`
- `docs/` — Architecture docs, library references, edit history

Each package follows `src/` layout. Projects depend on libs via `[tool.uv.sources]` workspace references.

## Key Libraries

| Library | Purpose | Docs |
|---------|---------|------|
| `sap-gui` | Cross-platform SAP GUI automation (COM on Windows, Scripting Console on macOS) | [docs/sap-gui.md](docs/sap-gui.md) |
| `qbi-crawler` | Quick BI dashboard export via Playwright | [docs/qbi-crawler.md](docs/qbi-crawler.md) |
| `excel-utils` | Shared openpyxl utilities (read, write, style) | [docs/excel-utils.md](docs/excel-utils.md) |
| `vpn` | SealSuite VPN automation (macOS: cliclick + log-based status) | [docs/vpn.md](docs/vpn.md) |

## SAP GUI Quick Reference

- **Platform dispatch**: `session.py` imports `_win32.py` or `_darwin.py` based on `sys.platform`
- **macOS auto-launch**: `SAPSession(auto_launch=True)` launches SAP GUI, connects, and polls for session readiness
- **macOS bridge**: AppleScript pastes JS into Scripting Console, reads results from temp files
- **KSB1 macOS**: `_run_darwin()` batches entire flow into one JS call (~38s vs ~150s)
- **macOS constraints**: DY_PATH read-only, cost centers via AWT clipboard, post-export modal bypassed via `startTransaction()`

## Commands

```bash
uv sync                              # Install all dependencies

# SAP GUI E2E test (macOS: auto-launches; Windows: requires live SAP session)
uv run --project libs/sap-gui python libs/sap-gui/tests/e2e_ksb1.py

# KSB1 accounting check
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --model qwen3:8b

# KSB1 GUI
python -m ksb1_accounting_check_gui
cd projects/ksb1-accounting-check-gui && python -m PyInstaller ksb1_gui.spec --noconfirm

# Daily store operation report
uv run --project projects/daily-store-operation-report python -m daily_store_operation_report.main 2026-02-10
uv run --project projects/daily-store-operation-report python -m daily_store_operation_report.main 2026-02-10 --skip-download --data-dir output/qbi

# VPN unit tests
uv run --project libs/vpn pytest libs/vpn/tests/test_darwin.py -v

# VPN e2e tests (requires live CorpLink + Accessibility permission)
uv run --project libs/vpn pytest libs/vpn/tests/test_e2e.py -v -s

# Tests
python -m pytest projects/ksb1-accounting-check/tests/ -v

# Playwright (one-time setup)
playwright install chromium
```

## Environment Variables

| Variable | Used by | Description |
|---|---|---|
| `SAP_USERNAME` / `SAP_PASSWORD` | sap-gui, projects | SAP login credentials |
| `SAP_LANGUAGE` | sap-gui, projects | SAP language code (default: `ZH`) |
| `SAP_CONNECTION` | sap-gui (macOS) | Override connection string (`/H/<host>/S/<port>`). Auto-detected from landscape XML if unset |
| `SAPGUI_APP` | sap-gui (macOS) | Override SAP GUI app path. Auto-detected from `/Applications/SAPGUI *.app` if unset |
| `SEALSUITE_EXE` | vpn | Override SealSuite executable path |

## Software Install Links

| Software | Link |
|----------|------|
| SAP GUI (macOS) | [Feishu Wiki — SAP GUI Mac 安装指南](https://haidilao.feishu.cn/wiki/DWcHwOsf0iLjvlkHeZncJpyhn0g) |
| SAP GUI (Windows) | [Feishu Doc — SAP GUI Windows 安装指南](https://haidilao.feishu.cn/docx/SWOkdCypPob5GOxOoXHcX8mvnO6) |
| SealSuite (飞连 VPN) | [Volcengine — 飞连下载](https://www.volcengine.com/product/feilian/download) |

## Key Conventions

- On Windows, SAP GUI must be open before running automations; on macOS, `auto_launch=True` starts it automatically
- SAP date format: `YYYY.MM.DD`
- Process-specific SAP flows live in `libs/sap-gui/src/sap_gui/processes/<name>/`; projects are thin CLI wrappers
- Process data files (cost center lists, mappings) live alongside their process module
- Use `pathlib.Path` for all file path parameters and return types
- Environment/config loading is the project entry point's responsibility, not libs'
- New libs go in `libs/`, new automations go in `projects/`

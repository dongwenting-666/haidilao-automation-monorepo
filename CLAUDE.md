# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Monorepo for Haidilao paperwork automations. Uses **uv workspaces** with Python >= 3.13 and **hatchling** as the build backend.

## Repository Layout

- `libs/` — Shared libraries consumed by projects (e.g., `sap-gui`)
- `projects/` — Standalone automation scripts (e.g., `ksb1-accounting-check`)
- Each package follows `src/` layout: `src/<package_name>/`
- `output/` — Default export destination (gitignored)

Projects depend on libs via workspace references (`[tool.uv.sources]` in their `pyproject.toml`).

## SAP GUI Library Structure

```
libs/sap-gui/src/sap_gui/
    errors.py          # Exception hierarchy (SAPGuiError, SAPConnectionError, etc.)
    session.py         # COM connection (SAPSession, SAPSessionManager)
    navigation.py      # Transaction/field/button helpers (SAPNavigator)
    export.py          # File export (SAPExporter — ALV grid + classic list)
    processes/         # Process-specific automation modules
        ksb1/          # KSB1 cost center report export
            __init__.py        # execute(), run(), helpers
            cost_centers.txt   # Default cost center list
```

## KSB1 Accounting Check Structure

```
projects/ksb1-accounting-check/src/ksb1_accounting_check/
    main.py            # CLI entry point (argparse, SAP download + report generation)
    analyze.py         # Data loading, enrichment, per-store comparison, XLSX report
    rules.py           # Deterministic rule-based analysis (replaces former LLM analysis)
    llm.py             # LLM-based analysis (kept for future use, not currently imported)
    prompt.md          # LLM prompt reference (kept for future use)
    报表科目.xlsx       # Cost element → 报表科目 mapping spreadsheet
```

### Analysis Rules (`rules.py`)

The KSB1 accounting check uses deterministic rules instead of LLM calls:
- **Skipped kemus**: `SKIP_KEMUS` — high-volume routine items excluded from analysis
- **Key cost elements**: `KEY_COST_ELEMENTS` — always reported when they change (threshold: 100 CAD)
- **General thresholds**: minimum absolute difference of 500 CAD **and** 20% change
- **Presence checks**: flags cost elements present in one month but absent in the other
- Uses `对象货币值` (object currency / local CAD) for amounts, not `报表货币值`

## Commands

```bash
# Install all dependencies
uv sync

# Run KSB1 export (defaults to previous month, output to <repo>/output/)
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Run tests for KSB1 accounting check
python -m pytest projects/ksb1-accounting-check/tests/ -v

# Add a dependency to a specific package
uv add --project libs/sap-gui <package>
```

## Key Conventions

- SAP GUI 770 must be open before running automations — `sap-gui` uses COM/ActiveX via `pywin32` to connect to the running SAP GUI process (login is handled automatically)
- SAP date format is `YYYY.MM.DD` (not DD.MM.YYYY)
- Process-specific SAP flows live in `libs/sap-gui/src/sap_gui/processes/<name>/`; projects are thin CLI wrappers
- Process data files (e.g., cost center lists) live alongside their process module, not in the project
- Use `pathlib.Path` for all file path parameters and return types
- Environment/config loading is the responsibility of the project entry point, not shared libs
- New libs go in `libs/`, new automations go in `projects/`

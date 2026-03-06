# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Monorepo for Haidilao paperwork automations. Uses **uv workspaces** with Python >= 3.13 and **hatchling** as the build backend.

## Repository Layout

- `libs/` — Shared libraries consumed by projects (e.g., `sap-file-downloader`)
- `projects/` — Standalone automation scripts (e.g., `ksb1-accounting-check`)
- Each package follows `src/` layout: `src/<package_name>/`

Projects depend on libs via workspace references (`[tool.uv.sources]` in their `pyproject.toml`).

## Commands

```bash
# Install all dependencies
uv sync

# Run a specific project
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Add a dependency to a specific package
uv add --project libs/sap-file-downloader <package>
```

## Key Conventions

- Environment variables for SAP config (`SAP_USERNAME`, `SAP_PASSWORD`, `SAP_HOST`, `SAP_PORT`); loaded via `python-dotenv` inside `main()`, never at module level
- Use `pathlib.Path` for all file path parameters and return types
- Shared libs should not depend on `python-dotenv` — env loading is the responsibility of the project entry point
- New libs go in `libs/`, new automations go in `projects/`

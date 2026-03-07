# Haidilao Automation Monorepo

Monorepo for Haidilao paperwork automations, managed with [uv workspaces](https://docs.astral.sh/uv/concepts/workspaces/).

## Structure

```
├── libs/                      # Shared libraries
│   └── sap-gui/                 # SAP GUI automation (COM/ActiveX)
│       └── processes/ksb1/      # KSB1 export process + cost centers
├── projects/                  # Automation projects (thin CLI wrappers)
│   └── ksb1-accounting-check/   # KSB1 accounting check CLI
├── output/                    # Default export destination (gitignored)
```

## Prerequisites

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- SAP GUI 770 (SAP Logon for Windows) — must be open before running automations
- SAP GUI Scripting must be enabled (in SAP GUI options)
- Scripting security popups disabled (see registry settings in CLAUDE.md memory)

## Setup

```bash
# Clone and install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SAP_USERNAME` | SAP login username |
| `SAP_PASSWORD` | SAP login password |

## Projects

### KSB1 Accounting Check

Exports KSB1 (Cost Center: Actual Line Items) report to an XLSX file.

```bash
# Export previous month (default) — output to <repo>/output/
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Custom date range and output directory
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main \
    --date-from 2026-01-01 --date-to 2026-01-31 \
    --output-dir G:/output
```

Cost centers are defined in `libs/sap-gui/src/sap_gui/processes/ksb1/cost_centers.txt`. Credentials come from `.env` or `--username`/`--password` flags.

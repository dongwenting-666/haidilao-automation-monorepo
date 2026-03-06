# Haidilao Automation Monorepo

Monorepo for Haidilao paperwork automations, managed with [uv workspaces](https://docs.astral.sh/uv/concepts/workspaces/).

## Structure

```
├── libs/                  # Shared libraries
│   └── sap-file-downloader/   # SAP file download automation
├── projects/              # Automation projects
│   └── ksb1-accounting-check/ # KSB1 accounting check
```

## Prerequisites

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
# Clone and install dependencies
uv sync

# Copy and configure environment variables
cp .env.example .env
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SAP_USERNAME` | SAP login username | |
| `SAP_PASSWORD` | SAP login password | |
| `SAP_HOST` | SAP server hostname | |
| `SAP_PORT` | SAP server port | `443` |

## Projects

### KSB1 Accounting Check

```bash
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main
```

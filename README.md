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

## Software Install Links

| Software | Link |
|----------|------|
| SAP GUI (macOS) | [Feishu Wiki — SAP GUI Mac 安装指南](https://haidilao.feishu.cn/wiki/DWcHwOsf0iLjvlkHeZncJpyhn0g) |
| SAP GUI (Windows) | [Feishu Doc — SAP GUI Windows 安装指南](https://haidilao.feishu.cn/docx/SWOkdCypPob5GOxOoXHcX8mvnO6) |
| SealSuite (飞连 VPN) | [Volcengine — 飞连下载](https://www.volcengine.com/product/feilian/download) |

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

Downloads KSB1 (Cost Center: Actual Line Items) data from SAP, then generates a month-over-month comparison report per store using **deterministic rule-based analysis**. The output is an XLSX workbook with one sheet per store (findings + detail rows), a raw data sheet, and a mapping reference sheet.

Analysis highlights:
- Cost elements present in one month but missing in the other
- Significant amount differences (>500 CAD and >20% change)
- Key cost elements (rent, utilities, insurance, etc.) flagged at a lower threshold (>100 CAD)
- Report generation takes ~1.5 seconds (no LLM dependency)

```bash
# Check previous month (default) — download from SAP + generate report
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main

# Check a specific month/year
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main 2 2026

# Skip SAP download, reuse existing KSB1 export
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main --skip-download

# Custom output directory
uv run --project projects/ksb1-accounting-check python -m ksb1_accounting_check.main \
    --output-dir G:/output
```

Cost centers are defined in `libs/sap-gui/src/sap_gui/processes/ksb1/cost_centers.txt`. Credentials come from `.env` or `--username`/`--password` flags.

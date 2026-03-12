# QBI Crawler

Web crawler library for Haidilao Quick BI dashboards using Playwright browser automation.

## Overview

Quick BI (`qbi.superhi-tech.com`) is Haidilao's overseas data portal built as a React/Ant Design SPA. The `qbi-crawler` library automates login, report navigation, date filtering, and XLSX export via headless Chromium.

## Architecture

```
libs/qbi-crawler/src/qbi_crawler/
    __init__.py        # Public API exports
    auth.py            # QBISession — browser lifecycle + LDAP login
    constants.py       # BASE_URL
    dashboard.py       # Report navigation, date setting, XLSX export
    errors.py          # QBIError, QBILoginError, QBITimeoutError
    py.typed           # PEP 561 marker
```

## Authentication (`auth.py`)

`QBISession` is a context manager that manages an authenticated Playwright session:

```python
from qbi_crawler import QBISession

with QBISession(username="user", password="pass") as session:
    page = session.page
    # navigate, extract data, screenshot, etc.
```

Key behaviors:
- **Auto-installs Chromium** on first use via `playwright install chromium` (thread-safe with double-checked locking)
- **LDAP login** — waits for dynamically rendered form inputs, fills credentials, submits
- **Password cleared** after login (`self._password = None`) for security
- **Safe cleanup** — nested try/finally in `__exit__` ensures browser/context always close, all instance state reset to None
- **Headless by default** — pass `headless=False` for debugging

## Dashboard Navigation (`dashboard.py`)

### Reports

Three reports are supported, identified by menuId:

| Constant | Report Name | menuId |
|----------|-------------|--------|
| `REPORT_DAILY` | 门店经营日报数据 | `89809ff6-...` |
| `REPORT_TIME_PERIOD` | 分时段营业数据 | `4ee6d680-...` |
| `REPORT_24H` | 24小时营业数据 | `2090b625-...` |

### Navigation Strategy

The portal uses iframes for dashboard content. Navigation uses **direct URL loading** rather than sidebar clicks because sidebar navigation destroys and recreates the iframe, causing `Frame was detached` errors.

### Public API

**`navigate_to_report(page, report_name)`** — Load a report by direct URL, wait for iframe and SPA rendering.

**`set_date_range(iframe, start, end)`** — Set date range filter using keyboard input (Ant Design DatePicker workaround: click → Ctrl+A → type → Enter → Escape).

**`export_excel(iframe, download_dir)`** — Click export button, select EXCEL format, confirm, and save downloaded file.

**`download_report(page, report_name, *, start_date, end_date, download_dir)`** — High-level function combining navigation + date + export.

### Usage Example

```python
from pathlib import Path
from qbi_crawler import QBISession, REPORT_DAILY, download_report

with QBISession(username="user", password="pass") as session:
    path = download_report(
        session.page,
        REPORT_DAILY,
        start_date="2026-02-01",
        end_date="2026-02-28",
        download_dir=Path("output/qbi"),
    )
    print(f"Downloaded: {path}")
```

## Timing Constants

All timeouts are named constants in `dashboard.py`:

| Constant | Value | Purpose |
|----------|-------|---------|
| `_NAVIGATION_SETTLE` | 3s | Wait after page.goto for SPA to settle |
| `_SPA_RENDER_WAIT` | 2s | Wait after selector found for full render |
| `_POST_QUERY_WAIT` | 5s | Wait after clicking 查询 for data load |
| `_IFRAME_TIMEOUT_MS` | 60s | Max wait for dashboard iframe to appear |
| `_SELECTOR_WAIT_TIMEOUT_MS` | 30s | Wait for date inputs/query button |
| `_EXPORT_BTN_TIMEOUT_MS` | 10s | Wait for export button |
| `_DOWNLOAD_TIMEOUT_MS` | 120s | Wait for file download to complete |

## Error Hierarchy

```
QBIError (base)
├── QBILoginError    — Authentication failure
└── QBITimeoutError  — Element/page timeout
```

## Environment Variables

```
QBI_USERNAME=       # LDAP/AD username
QBI_PASSWORD=       # LDAP/AD password
```

## Dependencies

- `playwright>=1.40` — Browser automation (Chromium)

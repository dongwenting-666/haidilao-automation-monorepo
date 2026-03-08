# SAP GUI Library (`libs/sap-gui`)

COM/ActiveX automation library for SAP GUI 770 (SAP Logon for Windows). Connects to an already-running SAP GUI process via `pywin32`.

## Prerequisites

- SAP GUI 770 must be open (the library does NOT launch SAP)
- SAP GUI Scripting enabled (SAP GUI Options > Accessibility & Scripting)
- Security popups disabled (via registry or SAP GUI settings)

## Module Structure

```
libs/sap-gui/src/sap_gui/
    __init__.py        # Public API exports
    errors.py          # Exception hierarchy
    session.py         # COM connection management
    navigation.py      # Transaction/field/button interaction
    export.py          # File export (ALV grid + classic list)
    processes/         # Transaction-specific automation flows
        ksb1/
            __init__.py        # KSB1 export: execute(), run()
            cost_centers.txt   # Default cost center list
```

## API Reference

### Exceptions (`errors.py`)

| Exception | Description |
|-----------|-------------|
| `SAPGuiError` | Base exception for all SAP GUI errors |
| `SAPConnectionError` | SAP GUI not running or no session found |
| `SAPNavigationError` | Transaction navigation or field interaction failed |
| `SAPExportError` | File export operation failed |
| `SAPStatusBarError` | Status bar shows error/abort message (has `.message_text` and `.message_type`) |

### SAPSession (`session.py`)

Single-session connection to a running SAP GUI instance.

```python
from sap_gui import SAPSession

with SAPSession() as sap:
    raw_session = sap.session  # GuiSession COM object
```

- `__init__(connection_index=None, session_index=0)` — Which connection/session to attach to. `None` auto-finds the first responsive connection.
- `connect()` / `disconnect()` — Manage COM lifecycle (called automatically by context manager)
- `session` property — Raw `GuiSession` COM object

### SAPSessionManager (`session.py`)

Multi-session manager for parallel automation. Handles login and session creation.

```python
from sap_gui import SAPSessionManager

with SAPSessionManager("user", "pass") as mgr:
    primary = mgr.primary_session
    results = mgr.run_parallel(tasks, max_sessions=5)
```

- `__init__(username, password, language="ZH")`
- `connect()` — Connect and log in (auto-called by context manager)
- `create_session()` — Create an additional SAP session (returns raw COM object)
- `primary_session` property — The first logged-in session
- `run_parallel(tasks, max_sessions=5)` — Run callables in parallel; each receives `(session, navigator, exporter)`

### SAPNavigator (`navigation.py`)

Field interaction and transaction navigation.

```python
from sap_gui import SAPNavigator

nav = SAPNavigator(sap.session)
nav.login("user", "pass")
nav.run_transaction("KSB1")
nav.set_field("wnd[0]/usr/ctxtKOSTL-LOW", "1000")
nav.send_vkey(8)  # F8 = Execute
```

| Method | Description |
|--------|-------------|
| `login(username, password, language="ZH")` | Log in from SAP login screen; skips if already authenticated |
| `run_transaction(tcode)` | Navigate to transaction (e.g., `"KSB1"`) |
| `set_field(field_id, value)` | Set text field by SAP element ID |
| `press_button(button_id)` | Press button by element ID |
| `send_vkey(vkey, window=0)` | Send virtual key (0=Enter, 3=Back, 8=F8, 11=Save, 12=Cancel) |
| `check_status_bar()` | Raise `SAPStatusBarError` if status bar has error/abort |
| `select_menu(menu_id)` | Select menu item by element ID |
| `close_window(window=1)` | Close SAP window; returns `True` if successful |
| `dismiss_popup(window=1, vkey=0)` | Dismiss modal popup; returns `True` if dismissed |

### SAPExporter (`export.py`)

File export from SAP reports.

```python
from sap_gui import SAPExporter

exporter = SAPExporter(sap.session, nav)
exporter.export_list_to_file(Path("output/report.XLSX"))
```

| Method | Description |
|--------|-------------|
| `export_alv_to_file(output_path, grid_id=..., timeout=10.0)` | Export ALV grid via context menu > Spreadsheet |
| `export_list_to_file(output_path, menu_path=..., dialog_window=1, timeout=10.0)` | Export classic list via menu bar (List > Export > Spreadsheet) |

Both methods auto-create parent directories and wait for file creation (up to `timeout` seconds).

## Process Modules

### KSB1 (`processes/ksb1/`)

Automates KSB1 (Cost Center: Actual Line Items) report export.

```python
from sap_gui.processes.ksb1 import run, DEFAULT_COST_CENTERS_FILE

# Standalone (handles login)
run(username="user", password="pass",
    cost_center_file=DEFAULT_COST_CENTERS_FILE,
    output_path=Path("output/ksb1.XLSX"),
    date_from=date(2025, 12, 1),
    date_to=date(2026, 1, 31))

# With existing session (for parallel use)
from sap_gui.processes.ksb1 import execute
execute(session, nav, exporter, cost_center_file, output_path, date_from, date_to)
```

**Key details:**
- SAP date format: `YYYY.MM.DD`
- Default max rows: `9,999,999`
- Cost centers uploaded via multi-select dialog from `cost_centers.txt`
- Uses `export_list_to_file` (classic list export, not ALV grid)

# SAP GUI Library (`libs/sap-gui`)

Cross-platform SAP GUI automation library. On Windows, connects via COM/ActiveX (`pywin32`). On macOS, bridges to SAP GUI for Java's Scripting Console (AppleScript + Nashorn JS engine).

## Prerequisites

### Windows
- SAP GUI 770 must be open (the library does NOT launch SAP on Windows)
- SAP GUI Scripting enabled (SAP GUI Options > Accessibility & Scripting)
- Security popups disabled (via registry or SAP GUI settings)

### macOS
- SAP GUI for Java installed in `/Applications/` (or set `SAPGUI_APP` env var)
- Accessibility permission for your terminal app (System Settings > Privacy & Security > Accessibility)
- With `auto_launch=True`, SAP GUI is started automatically; without it, SAP GUI must already be running and connected

## Module Structure

```
libs/sap-gui/src/sap_gui/
    __init__.py        # Public API exports
    errors.py          # Exception hierarchy
    session.py         # Platform dispatcher — imports _win32 or _darwin
    _win32.py          # Windows: COM/ActiveX via pywin32
    _darwin.py         # macOS: Scripting Console bridge (AppleScript + Nashorn JS)
    navigation.py      # Transaction/field/button interaction
    export.py          # File export (ALV grid + classic list)
    processes/         # Transaction-specific automation flows
        ksb1/
            __init__.py        # KSB1 export: execute(), run(), _run_darwin()
            cost_centers.txt   # Default cost center list
libs/sap-gui/tests/
    e2e_ksb1.py        # End-to-end KSB1 test (requires live SAP session)
```

### Cross-Platform Architecture

- **`session.py`** dispatches to `_win32.py` (Windows) or `_darwin.py` (macOS) based on `sys.platform`
- Public API is identical: `SAPSession`, `SAPSessionManager`, `SAPNavigator`, `SAPExporter`
- Platform-conditional behaviour in `export.py` (DY_PATH), `navigation.py` (startTransaction), `ksb1/__init__.py` (batched JS)

### macOS Bridge (`_darwin.py`)

- Uses SAP GUI for Java's built-in **Scripting Console** (Nashorn JS engine)
- IPC: JS writes results to temp files via `java.io.FileWriter`, Python reads them
- AppleScript automates paste-and-run into the console
- `_SAPElement` / `_SAPInfo` proxy objects convert PascalCase to camelCase for Java API compatibility
- IIFE wrapping `(function(){...})()` prevents Nashorn scope collisions across runs
- `_MIN_INTERVAL = 0.6s` throttle between consecutive calls to prevent clipboard/focus races
- `_execute_with_retry` handles console loss after screen transitions by re-opening and retrying once

### macOS Auto-Launch

`SAPSession(auto_launch=True)` makes automation fully hands-free:
- Launches SAP GUI for Java via `open <app> --args -o "/H/<host>/S/<port>" -b`
- Connection string auto-detected from: `SAP_CONNECTION` env var, then `~/Library/Preferences/SAP/SAPGUILandscape.xml`
- Handles 3 scenarios:
  1. **Not running** — launch with connection string, poll until login screen reachable
  2. **Running but stale** (no usable session) — kill process, relaunch, poll
  3. **Running with session** — connect immediately
- `_poll_for_session()` probes bridge with short per-probe timeouts until `ses.info.systemName` succeeds

### macOS-Specific Constraints

- **Security Access Violation**: SAP GUI for Java blocks custom DY_PATH in save dialogs. Fix: read default path, only set filename, then `shutil.move`
- **Cost center import**: File import blocked by security. Fix: uses Java AWT clipboard (`btn[24]`) instead of file dialog (`btn[23]`)
- **Post-export modal**: Persistent GuiModalWindow after export. Fix: `ses.startTransaction()` bypasses it
- **`open --args` idempotency**: macOS `open` only passes `--args` when launching a new process; if already running, args are silently ignored

## Environment Variables

| Variable | Platform | Description |
|---|---|---|
| `SAP_CONNECTION` | macOS | Override SAP connection string (`/H/<host>/S/<port>`). Auto-detected from landscape XML if unset |
| `SAPGUI_APP` | macOS | Override SAP GUI app bundle path. Auto-detected from `/Applications/SAPGUI *.app` if unset |

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

Single-session connection to a SAP GUI instance. Platform-dispatched: uses COM on Windows, Scripting Console bridge on macOS.

```python
from sap_gui import SAPSession

# Windows: attach to running SAP GUI
with SAPSession() as sap:
    raw_session = sap.session

# macOS: auto-launch SAP GUI if not running
with SAPSession(auto_launch=True) as sap:
    raw_session = sap.session
```

- `__init__(connection_index=None, session_index=0, *, auto_launch=False, connection_string=None)`
  - `connection_index` / `session_index`: Which connection/session to attach to (Windows only; ignored on macOS)
  - `auto_launch`: If True, launch SAP GUI automatically on macOS (logged as warning on Windows)
  - `connection_string`: Override SAP connection string for auto-launch (macOS only)
- `connect()` / `disconnect()` — Manage lifecycle (called automatically by context manager)
- `session` property — Raw `GuiSession` COM object (Windows) or self (macOS, implements `findById()`)

### SAPSessionManager (`session.py`)

Multi-session manager for parallel automation. Handles login and session creation. Windows only; macOS raises `NotImplementedError`.

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

Field interaction and transaction navigation. Works identically on both platforms.

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
| `run_transaction(tcode)` | Navigate to transaction (uses `startTransaction()` on macOS, okcd + Enter on Windows) |
| `set_field(field_id, value)` | Set text field by SAP element ID |
| `press_button(button_id)` | Press button by element ID |
| `send_vkey(vkey, window=0)` | Send virtual key (0=Enter, 3=Back, 8=F8, 11=Save, 12=Cancel) |
| `check_status_bar()` | Raise `SAPStatusBarError` if status bar has error/abort |
| `select_menu(menu_id)` | Select menu item by element ID |
| `close_window(window=1)` | Close SAP window; returns `True` if successful |
| `dismiss_popup(window=1, vkey=0)` | Dismiss modal popup; returns `True` if dismissed |

### SAPExporter (`export.py`)

File export from SAP reports. Handles platform differences in save dialog (DY_PATH read-only on macOS).

```python
from sap_gui import SAPExporter

exporter = SAPExporter(sap.session, nav)
exporter.export_list_to_file(Path("output/report.XLSX"))
```

| Method | Description |
|--------|-------------|
| `export_alv_to_file(output_path, grid_id=..., timeout=10.0)` | Export ALV grid via context menu > Spreadsheet |
| `export_list_to_file(output_path, menu_path=..., dialog_window=1, timeout=10.0)` | Export classic list via menu bar (List > Export > Spreadsheet) |

Both methods auto-create parent directories and wait for file creation (up to `timeout` seconds). On macOS, files are saved to SAP's default directory then moved to `output_path` via `shutil.move`.

## Process Modules

### KSB1 (`processes/ksb1/`)

Automates KSB1 (Cost Center: Actual Line Items) report export.

```python
from sap_gui.processes.ksb1 import run, DEFAULT_COST_CENTERS_FILE

# Standalone (handles login; auto-launches SAP GUI on macOS)
run(username="user", password="pass",
    cost_center_file=DEFAULT_COST_CENTERS_FILE,
    output_path=Path("output/ksb1.XLSX"),
    date_from=date(2025, 12, 1),
    date_to=date(2026, 1, 31))

# With existing session (for parallel use, Windows only)
from sap_gui.processes.ksb1 import execute
execute(session, nav, exporter, cost_center_file, output_path, date_from, date_to)
```

**Key details:**
- SAP date format: `YYYY.MM.DD`
- Default max rows: `9,999,999`
- Cost centers validated with `isalnum()` to prevent JS injection
- On Windows: uploaded via multi-select dialog file import (`btn[23]`)
- On macOS: uploaded via Java AWT clipboard (`btn[24]`), batched into a single JS call for performance (~38s vs ~150s)
- Uses `export_list_to_file` (classic list export, not ALV grid)

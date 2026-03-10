# KSB1 Accounting Check GUI (`projects/ksb1-accounting-check-gui`)

Desktop GUI application for the KSB1 accounting check. Packages as a standalone Windows EXE — no Python installation required.

## Module Structure

```
projects/ksb1-accounting-check-gui/
├── src/ksb1_accounting_check_gui/
│   ├── __init__.py      # Package marker
│   ├── __main__.py      # Entry point (python -m ksb1_accounting_check_gui)
│   ├── app.py           # tkinter GUI (App class, main window)
│   ├── worker.py        # Background worker functions (SAP download + report generation)
│   ├── paths.py         # Resource path resolution (PyInstaller frozen vs dev mode)
│   └── log_handler.py   # Thread-safe logging to tkinter Text widget
├── ksb1_gui.spec        # PyInstaller spec (single-file EXE)
├── dist/                # Built EXE output (gitignored)
├── build/               # PyInstaller build artifacts (gitignored)
└── pyproject.toml
```

## Running in Development

```bash
# From repo root
python -m ksb1_accounting_check_gui
```

Requires workspace packages to be installed (`pip install -e` or via `uv`).

## Building the EXE

```bash
cd projects/ksb1-accounting-check-gui
python -m PyInstaller ksb1_gui.spec --noconfirm
```

Output: `dist/KSB1会计检查.exe` (~34 MB single file)

### Bundled Data Files

The EXE bundles these data files into a `data/` directory inside the archive:

| File | Source Location |
|------|----------------|
| `报表科目.xlsx` | `projects/ksb1-accounting-check/src/ksb1_accounting_check/` |
| `cost_centers.txt` | `libs/sap-gui/src/sap_gui/processes/ksb1/` |
| `prompt.md` | `projects/ksb1-accounting-check/src/ksb1_accounting_check/` |

At runtime, `paths.resource_path()` resolves these from `sys._MEIPASS/data/` (frozen) or from actual monorepo source locations (dev).

## GUI Features

| Section | Controls |
|---------|----------|
| SAP 登录 | Username, password (with show/hide toggle) |
| 设置 | Month (1-12), year (2020-2030), language (ZH/EN) |
| 输出目录 | Text field + browse button |
| LLM 增强 | Editable model combobox (presets: qwen3:8b/14b/32b, or type custom) |
| 操作 | "下载 SAP 数据 + 生成报告" / "仅生成报告（跳过下载）" |
| 日志 | Scrollable read-only log output |

### Defaults

- **Credentials**: Auto-loaded from `.env` file next to EXE, then from environment variables
- **Month/Year**: Previous month
- **Output directory**: `output/` next to EXE

## Architecture

### Threading Model

The GUI runs on the main thread (tkinter requirement). SAP download and report generation run in a background daemon thread to keep the UI responsive.

```
Main thread (tkinter)          Background thread (worker)
    │                              │
    ├── User clicks button         │
    ├── Disable buttons            │
    ├── Start daemon thread ──────>├── run_download_and_generate()
    │                              │   ├── SAP download
    │   ┌── poll log queue         │   ├── Report generation
    │   │   (every 100ms)          │   └── on_done(success, message)
    │   └──────────────────────────│──────────> root.after(0, _finish)
    ├── Re-enable buttons          │
    └── Show success/error dialog  │
```

### Thread-Safe Logging

`QueueLogHandler` bridges Python's `logging` module to the tkinter Text widget:
1. Worker thread calls `logging.info(...)`
2. Handler puts formatted message into `queue.Queue`
3. Main thread's `after()` callback drains queue into Text widget every 100ms
4. `winfo_exists()` guard prevents errors if widget is destroyed during polling

### Path Resolution

`paths.py` handles two modes:

| Mode | `resource_path()` | `exe_dir()` |
|------|-------------------|-------------|
| **Frozen** (EXE) | `sys._MEIPASS/data/<filename>` | Directory containing the EXE |
| **Development** | Actual monorepo source locations | Repo root (found by walking up to `pyproject.toml` with `[tool.uv.workspace]`) |

`_find_repo_root()` is cached with `@functools.cache` to avoid repeated filesystem walks.

### Error Handling

`worker._friendly_error()` maps known exceptions to user-friendly Chinese messages:

| Exception | Message |
|-----------|---------|
| `SAPConnectionError` | SAP GUI 未连接 + checklist |
| `SAPNavigationError` | SAP 操作失败 + checklist |
| `SAPExportError` | SAP 导出失败 + checklist |
| `SAPStatusBarError` | 检查 SAP 状态栏 |
| `OllamaConnectionError` | Ollama 连接失败 + checklist |
| `FileNotFoundError` | 文件未找到 |
| `PermissionError` | 权限不足，文件可能被占用 |

All errors include the original exception message for debugging.

## Rebuilding the EXE

The EXE is a frozen snapshot of the code. **Any code change requires rebuilding.**

```bash
cd projects/ksb1-accounting-check-gui
python -m PyInstaller ksb1_gui.spec --noconfirm
```

Takes ~45 seconds. The new EXE replaces the old one in `dist/`.

### What triggers a rebuild

- Any change to the GUI code (`app.py`, `worker.py`, `paths.py`, `log_handler.py`)
- Any change to the core library (`analyze.py`, `rules.py`, `llm.py`, `prompt.md`)
- Any change to `sap-gui` or `ollama-client` libs
- Any change to bundled data files (`报表科目.xlsx`, `cost_centers.txt`)

### What does NOT need a rebuild

- Changes to `.env` (loaded at runtime from next to the EXE)
- Changes to the output directory contents

## Distribution

To distribute the EXE:
1. Build with PyInstaller (see above)
2. Copy `dist/KSB1会计检查.exe` to the target machine
3. Optionally place a `.env` file next to the EXE with `SAP_USERNAME` and `SAP_PASSWORD`
4. SAP GUI must be installed and open before running

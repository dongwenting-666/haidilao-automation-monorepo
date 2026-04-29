"""ZFI0156 Store Actual Consumption Report (门店实际耗用数据统计表).

Automates the ZFI0156 transaction in SAP GUI:
1. Navigate to ZFI0156 (custom Z-tcode, dynpro ZHDL_FICO_REPORT_027.1000)
2. Set plant range (S_WERKS-LOW / S_WERKS-HIGH)
3. Set posting date range (S_BUDAT-LOW / S_BUDAT-HIGH)
4. Execute (F8) — result is a full-screen ALV grid
5. Export via menu List -> Export -> Spreadsheet (mbar/menu[0]/menu[3]/menu[1])
6. SAPLSFES save dialog: filename + confirm

The export menu path matches KSB1's default; there is no SAPLSPO5
format-chooser dialog (unlike MB5B), so we can reuse the standard
SAPExporter on Windows.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from sap_gui.errors import SAPExportError
from sap_gui.export import SAPExporter
from sap_gui.navigation import SAPNavigator
from sap_gui.session import SAPSession

log = logging.getLogger(__name__)

DEFAULT_PLANT_LOW = "CA01"
DEFAULT_PLANT_HIGH = "CA09"

# List -> Export -> Spreadsheet (same as SAPExporter._DEFAULT_MENU_PATH).
EXPORT_MENU_PATH = "wnd[0]/mbar/menu[0]/menu[3]/menu[1]"


def previous_month_range() -> tuple[date, date]:
    """Return (first_day, last_day) of the previous month."""
    first_of_this_month = date.today().replace(day=1)
    last_of_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    return first_of_prev, last_of_prev


def format_sap_text_date(d: date) -> str:
    """Format a date for SAP text fields (YYYY.MM.DD)."""
    return d.strftime("%Y.%m.%d")


def default_filename(d: date) -> str:
    """Default xlsx filename for a given month, e.g. zfi0156-202603.xlsx."""
    return f"zfi0156-{d.strftime('%Y%m')}.xlsx"


# ---------------------------------------------------------------------------
# macOS: login + single batched JS call for the rest
# ---------------------------------------------------------------------------

def _run_darwin(
    username: str,
    password: str,
    output_path: Path,
    plant_low: str,
    plant_high: str,
    date_from: date,
    date_to: date,
    language: str,
    export_timeout: float,
) -> Path:
    """macOS-optimised ZFI0156 flow: login + single JS call for everything."""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with SAPSession(auto_launch=True, quit_after=True) as sap:
        nav = SAPNavigator(sap.session)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        log.info(
            "Running ZFI0156 export: plants %s-%s, dates %s - %s",
            plant_low, plant_high,
            format_sap_text_date(date_from), format_sap_text_date(date_to),
        )

        js = (
            "(function() {"
            # Navigate to ZFI0156
            '  ses.startTransaction("ZFI0156");'
            # Plant range
            f'  ses.findById("wnd[0]/usr/ctxtS_WERKS-LOW").text = "{plant_low}";'
            f'  ses.findById("wnd[0]/usr/ctxtS_WERKS-HIGH").text = "{plant_high}";'
            # Posting date range
            f'  ses.findById("wnd[0]/usr/ctxtS_BUDAT-LOW").text = '
            f'"{format_sap_text_date(date_from)}";'
            f'  ses.findById("wnd[0]/usr/ctxtS_BUDAT-HIGH").text = '
            f'"{format_sap_text_date(date_to)}";'
            # F8 execute (blocks while SAP runs the report)
            '  ses.findById("wnd[0]").sendVKey(8);'
            # Export: List -> Export -> Spreadsheet (no format dialog)
            f'  ses.findById("{EXPORT_MENU_PATH}").select();'
            # Save dialog: read default dir, set filename, confirm
            '  var p = "" + ses.findById("wnd[1]/usr/ctxtDY_PATH").text;'
            f"  ses.findById(\"wnd[1]/usr/ctxtDY_FILENAME\").text = "
            f"{json.dumps(output_path.name)};"
            '  ses.findById("wnd[1]").sendVKey(0);'
            # Optional "replace existing file?" popup
            '  try { ses.findById("wnd[2]").sendVKey(0); } catch(e) {}'
            # Reset to main menu so no result/save windows are left open
            '  try { ses.startTransaction("SESSION_MANAGER"); } catch(e) {}'
            "  return p;"
            "})()"
        )

        actual_dir = sap.session.execute_js(
            js, timeout=300.0 + export_timeout,
        )

        if not actual_dir:
            raise SAPExportError("SAP did not return a save directory (DY_PATH)")
        actual_path = (Path(actual_dir) / output_path.name).resolve()
        t0 = time.monotonic()
        while not actual_path.exists():
            if time.monotonic() - t0 > export_timeout:
                raise SAPExportError(
                    f"Export file not created at {actual_path} "
                    f"within {export_timeout}s"
                )
            time.sleep(0.5)

        if actual_path != output_path:
            shutil.move(actual_path, output_path)

        log.info("Export complete: %s", output_path)
        return output_path


# ---------------------------------------------------------------------------
# Windows: individual bridge calls (COM)
# ---------------------------------------------------------------------------

def execute(
    session: object,
    nav: SAPNavigator,
    exporter: SAPExporter,
    output_path: Path,
    plant_low: str = DEFAULT_PLANT_LOW,
    plant_high: str = DEFAULT_PLANT_HIGH,
    date_from: date | None = None,
    date_to: date | None = None,
    export_timeout: float = 300.0,
) -> Path:
    """Run ZFI0156 on an already-authenticated session. Returns the saved path."""
    default_from, default_to = previous_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Navigate
    log.info("Navigating to ZFI0156...")
    nav.run_transaction("ZFI0156")

    # 2. Plant range
    log.info("Setting plant range: %s - %s", plant_low, plant_high)
    nav.set_field("wnd[0]/usr/ctxtS_WERKS-LOW", plant_low)
    nav.set_field("wnd[0]/usr/ctxtS_WERKS-HIGH", plant_high)

    # 3. Posting date range
    log.info(
        "Setting date range: %s - %s",
        format_sap_text_date(date_from), format_sap_text_date(date_to),
    )
    nav.set_field("wnd[0]/usr/ctxtS_BUDAT-LOW", format_sap_text_date(date_from))
    nav.set_field("wnd[0]/usr/ctxtS_BUDAT-HIGH", format_sap_text_date(date_to))

    # 4. Execute (F8)
    log.info("Executing ZFI0156...")
    nav.send_vkey(8)

    # 5. Export via menu — same menu path as SAPExporter's default.
    log.info("Exporting to %s", output_path)
    result = exporter.export_list_to_file(
        output_path,
        menu_path=EXPORT_MENU_PATH,
        timeout=export_timeout,
    )

    # 6. Return to main menu
    log.info("Returning to main menu...")
    try:
        nav.run_transaction("SESSION_MANAGER")
    except Exception:
        try:
            nav.send_vkey(3)
        except Exception:
            pass

    log.info("Export complete: %s", result)
    return result


def run(
    username: str,
    password: str,
    output_path: Path,
    plant_low: str = DEFAULT_PLANT_LOW,
    plant_high: str = DEFAULT_PLANT_HIGH,
    date_from: date | None = None,
    date_to: date | None = None,
    language: str = "ZH",
    export_timeout: float = 300.0,
) -> Path:
    """Run the full ZFI0156 export flow (login + execute). Returns the saved path."""
    default_from, default_to = previous_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to

    if sys.platform == "darwin":
        return _run_darwin(
            username, password, output_path,
            plant_low, plant_high,
            date_from, date_to, language, export_timeout,
        )

    with SAPSession() as sap:
        nav = SAPNavigator(sap.session)
        exporter = SAPExporter(sap.session, nav)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        return execute(
            sap.session, nav, exporter, output_path,
            plant_low, plant_high,
            date_from, date_to, export_timeout,
        )

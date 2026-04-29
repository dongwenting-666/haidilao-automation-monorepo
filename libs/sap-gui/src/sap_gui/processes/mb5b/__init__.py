"""MB5B Stock on Posting Date (库存) report export.

Automates the MB5B transaction in SAP GUI:
1. Navigate to MB5B
2. Set company code range (BUKRS-LOW / BUKRS-HIGH)
3. Set posting date range (DATUM-LOW / DATUM-HIGH)
4. Execute (F8)
5. Save via menu System -> List -> Save -> Local File (mbar/menu[0]/menu[1]/menu[2])
6. Pick "Spreadsheet" in the SAPLSPO5 format dialog (radSPOPLI-SELFLAG[1,0])
7. Set filename in the SAPLSFES save dialog and confirm
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
from sap_gui.navigation import SAPNavigator
from sap_gui.session import SAPSession

log = logging.getLogger(__name__)

DEFAULT_COMPANY_LOW = "9451"
DEFAULT_COMPANY_HIGH = "9452"

# Menu path differs from KSB1: System -> List -> Save -> Local File
SAVE_MENU_PATH = "wnd[0]/mbar/menu[0]/menu[1]/menu[2]"
# SAPLSPO5 = export-format chooser; index [1,0] = Spreadsheet
FORMAT_RADIO_SPREADSHEET = (
    "wnd[1]/usr/subSUBSCREEN_STEPLOOP:SAPLSPO5:0150"
    "/sub:SAPLSPO5:0150/radSPOPLI-SELFLAG[1,0]"
)


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
    """Default xlsx filename for a given month, e.g. mb5b202603.xlsx."""
    return f"mb5b{d.strftime('%Y%m')}.xlsx"


# ---------------------------------------------------------------------------
# macOS: login + single batched JS call for the rest
# ---------------------------------------------------------------------------

def _run_darwin(
    username: str,
    password: str,
    output_path: Path,
    company_low: str,
    company_high: str,
    date_from: date,
    date_to: date,
    language: str,
    export_timeout: float,
) -> Path:
    """macOS-optimised MB5B flow: login + single JS call for everything."""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with SAPSession(auto_launch=True, quit_after=True) as sap:
        nav = SAPNavigator(sap.session)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        log.info(
            "Running MB5B export: company %s-%s, dates %s - %s",
            company_low, company_high,
            format_sap_text_date(date_from), format_sap_text_date(date_to),
        )

        js = (
            "(function() {"
            # Navigate to MB5B
            '  ses.startTransaction("MB5B");'
            # Company code range
            f'  ses.findById("wnd[0]/usr/ctxtBUKRS-LOW").text = "{company_low}";'
            f'  ses.findById("wnd[0]/usr/ctxtBUKRS-HIGH").text = "{company_high}";'
            # Posting date range
            f'  ses.findById("wnd[0]/usr/ctxtDATUM-LOW").text = '
            f'"{format_sap_text_date(date_from)}";'
            f'  ses.findById("wnd[0]/usr/ctxtDATUM-HIGH").text = '
            f'"{format_sap_text_date(date_to)}";'
            # F8 execute (blocks while SAP processes)
            '  ses.findById("wnd[0]").sendVKey(8);'
            # System -> List -> Save -> Local File
            f'  ses.findById("{SAVE_MENU_PATH}").select();'
            # Format dialog (SAPLSPO5): pick Spreadsheet, OK
            f'  ses.findById("{FORMAT_RADIO_SPREADSHEET}").select();'
            '  ses.findById("wnd[1]/tbar[0]/btn[0]").press();'
            # File save dialog (SAPLSFES): read default dir, set filename, confirm
            '  var p = "" + ses.findById("wnd[1]/usr/ctxtDY_PATH").text;'
            f"  ses.findById(\"wnd[1]/usr/ctxtDY_FILENAME\").text = "
            f"{json.dumps(output_path.name)};"
            '  ses.findById("wnd[1]").sendVKey(0);'
            # Optional "replace existing?" popup
            '  try { ses.findById("wnd[2]").sendVKey(0); } catch(e) {}'
            # Return to main menu so no result/export windows are left open
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
    output_path: Path,
    company_low: str = DEFAULT_COMPANY_LOW,
    company_high: str = DEFAULT_COMPANY_HIGH,
    date_from: date | None = None,
    date_to: date | None = None,
    export_timeout: float = 300.0,
) -> Path:
    """Run MB5B on an already-authenticated session. Returns the saved path."""
    default_from, default_to = previous_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Navigate to MB5B
    log.info("Navigating to MB5B...")
    nav.run_transaction("MB5B")

    # 2. Company code range
    log.info("Setting company code range: %s - %s", company_low, company_high)
    nav.set_field("wnd[0]/usr/ctxtBUKRS-LOW", company_low)
    nav.set_field("wnd[0]/usr/ctxtBUKRS-HIGH", company_high)

    # 3. Posting date range
    log.info(
        "Setting date range: %s - %s",
        format_sap_text_date(date_from), format_sap_text_date(date_to),
    )
    nav.set_field("wnd[0]/usr/ctxtDATUM-LOW", format_sap_text_date(date_from))
    nav.set_field("wnd[0]/usr/ctxtDATUM-HIGH", format_sap_text_date(date_to))

    # 4. Execute (F8)
    log.info("Executing MB5B...")
    nav.send_vkey(8)

    # 5. Open save menu: System -> List -> Save -> Local File
    log.info("Opening save dialog via menu...")
    nav.select_menu(SAVE_MENU_PATH)

    # 6. Format dialog: select Spreadsheet, confirm
    log.info("Selecting Spreadsheet format...")
    try:
        session.findById(FORMAT_RADIO_SPREADSHEET).select()
    except Exception as exc:
        raise SAPExportError(
            "Failed to select Spreadsheet format in SAPLSPO5 dialog"
        ) from exc
    nav.press_button("wnd[1]/tbar[0]/btn[0]")

    # 7. File save dialog: wait for it (the format-dialog OK doesn't render
    #    the SAPLSFES window synchronously), then fill + confirm.
    log.info("Filling save dialog: %s", output_path.name)
    for _ in range(10):
        try:
            session.findById("wnd[1]/usr/ctxtDY_PATH").text  # noqa: B018
            break
        except Exception:
            time.sleep(1.0)
    else:
        raise SAPExportError(
            "SAPLSFES save dialog did not appear within 10s "
            "after Spreadsheet format selection"
        )

    try:
        actual_dir = str(session.findById("wnd[1]/usr/ctxtDY_PATH").text)
        # On macOS, SAP GUI for Java blocks DY_PATH writes (Security Access
        # Violation), so we keep the default download dir and shutil.move
        # afterwards. execute() also runs on darwin via parallel session
        # managers, so the platform guard is necessary, not redundant.
        if sys.platform != "darwin":
            session.findById("wnd[1]/usr/ctxtDY_PATH").text = str(
                output_path.parent
            )
            actual_dir = str(output_path.parent)
        session.findById("wnd[1]/usr/ctxtDY_FILENAME").text = output_path.name
    except Exception as exc:
        raise SAPExportError(
            "Failed to fill MB5B save dialog (SAPLSFES)"
        ) from exc
    nav.send_vkey(0)
    nav.dismiss_popup(window=2, vkey=0)

    # 8. Wait for file
    actual_path = (Path(actual_dir) / output_path.name).resolve()
    t0 = time.monotonic()
    while not actual_path.exists():
        if time.monotonic() - t0 > export_timeout:
            raise SAPExportError(
                f"Export file not created at {actual_path} within {export_timeout}s"
            )
        time.sleep(0.5)

    if actual_path != output_path:
        shutil.move(actual_path, output_path)

    # 9. Return to main menu
    log.info("Returning to main menu...")
    try:
        nav.run_transaction("SESSION_MANAGER")
    except Exception:
        try:
            nav.send_vkey(3)
        except Exception:
            pass

    log.info("Export complete: %s", output_path)
    return output_path


def run(
    username: str,
    password: str,
    output_path: Path,
    company_low: str = DEFAULT_COMPANY_LOW,
    company_high: str = DEFAULT_COMPANY_HIGH,
    date_from: date | None = None,
    date_to: date | None = None,
    language: str = "ZH",
    export_timeout: float = 300.0,
) -> Path:
    """Run the full MB5B export flow (login + execute). Returns the saved path."""
    default_from, default_to = previous_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to

    if sys.platform == "darwin":
        return _run_darwin(
            username, password, output_path,
            company_low, company_high,
            date_from, date_to, language, export_timeout,
        )

    with SAPSession() as sap:
        nav = SAPNavigator(sap.session)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        return execute(
            sap.session, nav, output_path,
            company_low, company_high,
            date_from, date_to, export_timeout,
        )

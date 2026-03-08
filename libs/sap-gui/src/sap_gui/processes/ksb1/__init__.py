"""KSB1 monthly cost center report export.

Automates the KSB1 transaction in SAP GUI:
1. Navigate to KSB1
2. Upload cost centers from a text file
3. Set date range
4. Execute the report
5. Export results to a local spreadsheet file
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from sap_gui.errors import SAPNavigationError
from sap_gui.export import SAPExporter
from sap_gui.navigation import SAPNavigator
from sap_gui.session import SAPSession

log = logging.getLogger(__name__)

DEFAULT_COST_CENTERS_FILE = Path(__file__).resolve().parent / "cost_centers.txt"


def previous_month_range() -> tuple[date, date]:
    """Return (first_day, last_day) of the previous month."""
    first_of_this_month = date.today().replace(day=1)
    last_of_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    return first_of_prev, last_of_prev


def format_sap_date(d: date) -> str:
    """Format a date for SAP text fields (YYYY.MM.DD)."""
    return d.strftime("%Y.%m.%d")


def _upload_cost_centers(nav: SAPNavigator, cost_center_file: Path) -> None:
    """Open the cost center multi-select and upload values from a text file."""
    cost_center_file = cost_center_file.resolve()
    if not cost_center_file.exists():
        raise FileNotFoundError(f"Cost center file not found: {cost_center_file}")

    # Open multi-select popup for cost center field
    nav.press_button("wnd[0]/usr/btn%_KOSTL_%_APP_%-VALU_PUSH")

    # btn[23] = "Import from text file" in the multi-select toolbar
    nav.press_button("wnd[1]/tbar[0]/btn[23]")

    # Fill the file path in the upload dialog and confirm
    nav.set_field("wnd[2]/usr/ctxtDY_PATH", str(cost_center_file.parent))
    nav.set_field("wnd[2]/usr/ctxtDY_FILENAME", cost_center_file.name)
    nav.press_button("wnd[2]/tbar[0]/btn[0]")

    # Confirm the multi-select list (green checkmark / btn[8] = Copy)
    nav.press_button("wnd[1]/tbar[0]/btn[8]")


def execute(
    session: object,
    nav: SAPNavigator,
    exporter: SAPExporter,
    cost_center_file: Path,
    output_path: Path,
    date_from: date | None = None,
    date_to: date | None = None,
    max_rows: int = 9999999,
) -> Path:
    """Run the KSB1 export on an already-authenticated session.

    Use this with SAPSessionManager for parallel execution.
    """
    default_from, default_to = previous_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to

    # 1. Navigate to KSB1
    log.info("Navigating to KSB1...")
    nav.run_transaction("KSB1")

    # 2. Upload cost centers from file
    log.info("Uploading cost centers from %s", cost_center_file)
    _upload_cost_centers(nav, cost_center_file)

    # 3. Set date range
    log.info("Setting date range: %s - %s", format_sap_date(date_from), format_sap_date(date_to))
    nav.set_field("wnd[0]/usr/ctxtR_BUDAT-LOW", format_sap_date(date_from))
    nav.set_field("wnd[0]/usr/ctxtR_BUDAT-HIGH", format_sap_date(date_to))

    # 4. Set max hit count via 更多设置 dialog
    log.info("Setting max hit count to %d...", max_rows)
    nav.press_button("wnd[0]/usr/btnBUT1")
    nav.set_field("wnd[1]/usr/txtKAEP_SETT-MAXSEL", str(max_rows))
    nav.press_button("wnd[1]/tbar[0]/btn[0]")

    # 5. Execute report (F8)
    log.info("Executing report...")
    nav.send_vkey(8)

    # 6. Export via menu: List → Export → Spreadsheet
    log.info("Exporting to %s", output_path)
    result = exporter.export_list_to_file(output_path)

    log.info("Export complete: %s", result)
    return result


def run(
    username: str,
    password: str,
    cost_center_file: Path,
    output_path: Path,
    date_from: date | None = None,
    date_to: date | None = None,
    language: str = "ZH",
    max_rows: int = 9999999,
) -> Path:
    """Run the full KSB1 export flow (login + export).

    Standalone entry point — connects, logs in, runs, disconnects.
    For parallel execution, use execute() with SAPSessionManager instead.
    """
    with SAPSession() as sap:
        nav = SAPNavigator(sap.session)
        exporter = SAPExporter(sap.session, nav)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        return execute(
            sap.session, nav, exporter,
            cost_center_file, output_path,
            date_from, date_to, max_rows,
        )

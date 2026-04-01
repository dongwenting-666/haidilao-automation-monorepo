"""F.13 Automatic Clearing (自动清帐) process.

Automates the F.13 transaction in SAP GUI:
1. Navigate to F.13
2. Set company code, fiscal year, posting date range
3. Optionally filter by GL account
4. Run in test mode or live mode
5. Press Enter to confirm execution
6. Scroll to bottom of result log and check for errors
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta

from sap_gui.errors import SAPNavigationError
from sap_gui.navigation import SAPNavigator
from sap_gui.session import SAPSession

log = logging.getLogger(__name__)

# Error keywords to search for in the result log
ERROR_KEYWORDS = ("错误", "Error", "异常", "Fehler", "ABEND", "失败")


def current_month_range() -> tuple[date, date]:
    """Return (first_day, last_day) of the current month."""
    today = date.today()
    first = today.replace(day=1)
    if today.month == 12:
        last = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    return first, last


def previous_month_range() -> tuple[date, date]:
    """Return (first_day, last_day) of the previous month."""
    first_of_this_month = date.today().replace(day=1)
    last_of_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    return first_of_prev, last_of_prev


def format_sap_text_date(d: date) -> str:
    """Format a date for SAP text fields (YYYY.MM.DD)."""
    return d.strftime("%Y.%m.%d")


def _check_errors(lines: list[str]) -> list[str]:
    """Return lines containing error keywords."""
    errors = []
    for line in lines:
        if any(kw in line for kw in ERROR_KEYWORDS):
            errors.append(line)
    return errors


# ---------------------------------------------------------------------------
# macOS: login + batched JS calls
# ---------------------------------------------------------------------------

def _run_darwin(
    username: str,
    password: str,
    company_code: str,
    date_from: date,
    date_to: date,
    fiscal_year: int | None,
    gl_account: str | None,
    test_run: bool,
    language: str,
) -> str:
    """macOS F.13 flow. Returns result summary."""
    fiscal_year = fiscal_year or date_from.year

    with SAPSession(auto_launch=True, quit_after=True) as sap:
        nav = SAPNavigator(sap.session)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        log.info("Running F.13 clearing...")

        # Step 1: Navigate + fill fields + execute
        fill_js = "(function() {\n"
        fill_js += '  ses.startTransaction("F.13");\n'
        fill_js += f'  ses.findById("wnd[0]/usr/ctxtBUKRX-LOW").text = "{company_code}";\n'
        fill_js += f'  ses.findById("wnd[0]/usr/txtGJAHX-LOW").text = "{fiscal_year}";\n'
        fill_js += f'  ses.findById("wnd[0]/usr/ctxtPOSTDATE-LOW").text = "{format_sap_text_date(date_from)}";\n'
        fill_js += f'  ses.findById("wnd[0]/usr/ctxtPOSTDATE-HIGH").text = "{format_sap_text_date(date_to)}";\n'

        if gl_account:
            fill_js += '  ses.findById("wnd[0]/usr/chkX_SAKNR").selected = true;\n'
            fill_js += f'  ses.findById("wnd[0]/usr/ctxtKONTS-LOW").text = "{gl_account}";\n'

        fill_js += f'  ses.findById("wnd[0]/usr/chkX_TESTL").selected = {"true" if test_run else "false"};\n'
        # F8 execute
        fill_js += '  ses.findById("wnd[0]/tbar[1]/btn[8]").press();\n'
        # Enter to confirm
        fill_js += '  ses.findById("wnd[0]").sendVKey(0);\n'
        fill_js += "})()"

        sap.session.execute_js(fill_js, timeout=600.0)

        # Step 2: Scroll to bottom and read result lines
        read_js = '''(function() {
            var lines = [];
            var usr = ses.findById("wnd[0]/usr");

            // Scroll to bottom
            try {
                var scr = null;
                try { scr = usr.findById("lcnt").verticalScrollbar; } catch(e) {}
                if (!scr) try { scr = usr.verticalScrollbar; } catch(e) {}
                if (!scr) try { scr = ses.findById("wnd[0]").verticalScrollbar; } catch(e) {}
                if (scr) { scr.position = scr.maximum; }
            } catch(e) {}

            // Read visible lines at bottom
            for (var r = 0; r < 30; r++) {
                try {
                    var txt = "" + usr.findById("lbl[0," + r + "]").text;
                    if (txt) lines.push(txt);
                } catch(e) { break; }
            }

            // Status bar
            try { lines.push("SBAR:" + ses.findById("wnd[0]/sbar").text); } catch(e) {}

            return lines.join("\\n");
        })()'''

        result_text = sap.session.execute_js(read_js, timeout=30.0) or ""

        # Check for errors
        result_lines = result_text.split("\n")
        errors = _check_errors(result_lines)

        if errors:
            log.error("F.13 completed with ERRORS:\n%s", "\n".join(errors))
        else:
            log.info("F.13 clearing completed successfully.")

        log.info("Result:\n%s", result_text)
        return result_text


# ---------------------------------------------------------------------------
# Windows: individual bridge calls (COM)
# ---------------------------------------------------------------------------

def execute(
    session: object,
    nav: SAPNavigator,
    company_code: str,
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: int | None = None,
    gl_account: str | None = None,
    test_run: bool = False,
) -> str:
    """Run F.13 on an already-authenticated session. Returns result summary.

    Args:
        session: SAP COM session object.
        nav: SAPNavigator for the session.
        company_code: SAP company code (e.g. "9451").
        date_from: Start of posting date range. Defaults to first of current month.
        date_to: End of posting date range. Defaults to last of current month.
        fiscal_year: Fiscal year. Defaults to date_from's year.
        gl_account: GL account to filter by (e.g. "22029999"). None = no filter.
        test_run: If True, run in test mode (no actual clearing).
    """
    default_from, default_to = current_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to
    fiscal_year = fiscal_year or date_from.year

    # 1. Navigate to F.13
    log.info("Navigating to F.13...")
    nav.run_transaction("F.13")

    # 2. Company code
    log.info("Setting company code: %s", company_code)
    nav.set_field("wnd[0]/usr/ctxtBUKRX-LOW", company_code)
    nav.send_vkey(0)

    # 3. Fiscal year
    log.info("Setting fiscal year: %d", fiscal_year)
    nav.set_field("wnd[0]/usr/txtGJAHX-LOW", str(fiscal_year))
    nav.send_vkey(0)

    # 4. Posting date range
    log.info("Setting date range: %s - %s", format_sap_text_date(date_from), format_sap_text_date(date_to))
    nav.set_field("wnd[0]/usr/ctxtPOSTDATE-LOW", format_sap_text_date(date_from))
    nav.set_field("wnd[0]/usr/ctxtPOSTDATE-HIGH", format_sap_text_date(date_to))

    # 5. GL account filter (optional)
    if gl_account:
        log.info("Filtering by GL account: %s", gl_account)
        try:
            session.findById("wnd[0]/usr/chkX_SAKNR").selected = True
        except Exception as exc:
            raise SAPNavigationError("Failed to check GL account checkbox") from exc
        nav.set_field("wnd[0]/usr/ctxtKONTS-LOW", gl_account)

    # 6. Test run toggle
    log.info("Test run: %s", test_run)
    try:
        session.findById("wnd[0]/usr/chkX_TESTL").selected = test_run
    except Exception as exc:
        raise SAPNavigationError("Failed to set test run checkbox") from exc

    # 7. Execute (F8)
    log.info("Executing F.13...")
    nav.press_button("wnd[0]/tbar[1]/btn[8]")

    # 8. Press Enter to confirm
    log.info("Confirming execution...")
    nav.send_vkey(0)

    # 9. Scroll to bottom of result log
    result_lines = []
    try:
        usr = session.findById("wnd[0]/usr")
        scr = getattr(usr, "verticalScrollbar", None)
        if scr:
            scr.position = scr.maximum
        # Read visible lines at bottom
        for r in range(30):
            try:
                txt = str(usr.findById(f"lbl[0,{r}]").text)
                if txt:
                    result_lines.append(txt)
            except Exception:
                break
    except Exception as exc:
        result_lines.append(f"(could not read result log: {exc})")

    # Status bar
    try:
        result_lines.append(f"SBAR:{session.findById('wnd[0]/sbar').text}")
    except Exception:
        pass

    result_text = "\n".join(result_lines)

    # Check for errors
    errors = _check_errors(result_lines)
    if errors:
        log.error("F.13 completed with ERRORS:\n%s", "\n".join(errors))
    else:
        log.info("F.13 clearing completed successfully.")

    # 10. Return to main menu
    log.info("Returning to main menu...")
    try:
        nav.run_transaction("SESSION_MANAGER")
    except Exception:
        try:
            nav.send_vkey(3)
        except Exception:
            pass

    log.info("Result:\n%s", result_text)
    return result_text


def run(
    username: str,
    password: str,
    company_code: str = "9451",
    date_from: date | None = None,
    date_to: date | None = None,
    fiscal_year: int | None = None,
    gl_account: str | None = None,
    test_run: bool = False,
    language: str = "ZH",
) -> str:
    """Run the full F.13 automatic clearing flow (login + execute). Returns result summary.

    Args:
        username: SAP username.
        password: SAP password.
        company_code: SAP company code. Defaults to "9451".
        date_from: Start of posting date range. Defaults to first of current month.
        date_to: End of posting date range. Defaults to last of current month.
        fiscal_year: Fiscal year. Defaults to date_from's year.
        gl_account: GL account to filter by (e.g. "22029999"). None = no filter.
        test_run: If True, run in test mode only (no actual postings).
        language: SAP language code. Defaults to "ZH".
    """
    default_from, default_to = current_month_range()
    date_from = date_from or default_from
    date_to = date_to or default_to
    fiscal_year = fiscal_year or date_from.year

    if sys.platform == "darwin":
        return _run_darwin(
            username, password, company_code,
            date_from, date_to, fiscal_year,
            gl_account, test_run, language,
        )

    with SAPSession() as sap:
        nav = SAPNavigator(sap.session)

        log.info("Logging in as %s...", username)
        nav.login(username, password, language)

        return execute(
            sap.session, nav,
            company_code, date_from, date_to,
            fiscal_year, gl_account, test_run,
        )

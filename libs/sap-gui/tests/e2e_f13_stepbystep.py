"""Step-by-step F.13 test — pauses between each action for visual inspection."""

from __future__ import annotations

import logging
import os
import sys
import time

from dotenv import load_dotenv
from vpn import ensure_vpn

from sap_gui.session import SAPSession
from sap_gui.navigation import SAPNavigator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PAUSE = 3  # seconds between steps


def pause(msg: str):
    log.info(">>> %s — waiting %ds...", msg, PAUSE)
    time.sleep(PAUSE)


def main():
    load_dotenv()
    username = os.environ.get("SAP_USERNAME", "")
    password = os.environ.get("SAP_PASSWORD", "")
    if not username or not password:
        print("ERROR: Set SAP_USERNAME and SAP_PASSWORD")
        sys.exit(1)

    log.info("Ensuring VPN...")
    ensure_vpn()

    log.info("Launching SAP GUI...")
    sap = SAPSession(auto_launch=True, quit_after=False)
    sap.__enter__()
    ses = sap.session
    nav = SAPNavigator(ses)

    try:
        # Step 1: Login
        log.info("STEP 1: Login as %s", username)
        nav.login(username, password, "ZH")
        pause("Logged in")

        # Step 2: Navigate to F.13
        log.info("STEP 2: Navigate to F.13")
        ses.execute_js('(function(){ ses.startTransaction("F.13"); })()')
        pause("At F.13 screen")

        # Step 3: Set company code
        log.info("STEP 3: Set company code = 9451")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/ctxtBUKRX-LOW").text = "9451"; })()')
        pause("Company code set")

        # Step 4: Set fiscal year
        log.info("STEP 4: Set fiscal year = 2026")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/txtGJAHX-LOW").text = "2026"; })()')
        pause("Fiscal year set")

        # Step 5: Set posting date from
        log.info("STEP 5: Set posting date from = 2026.03.01")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/ctxtPOSTDATE-LOW").text = "2026.03.01"; })()')
        pause("Date from set")

        # Step 6: Set posting date to
        log.info("STEP 6: Set posting date to = 2026.03.31")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/ctxtPOSTDATE-HIGH").text = "2026.03.31"; })()')
        pause("Date to set")

        # Step 7: Check GL account checkbox
        log.info("STEP 7: Check 'by GL account' checkbox")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/chkX_SAKNR").selected = true; })()')
        pause("GL account checkbox checked")

        # Step 8: Set GL account
        log.info("STEP 8: Set GL account = 22029999")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/ctxtKONTS-LOW").text = "22029999"; })()')
        pause("GL account set")

        # Step 9: Uncheck test run
        log.info("STEP 9: Uncheck test run")
        ses.execute_js('(function(){ ses.findById("wnd[0]/usr/chkX_TESTL").selected = false; })()')
        pause("Test run unchecked")

        # Step 10: Execute (F8)
        log.info("STEP 10: Press Execute (F8)")
        ses.execute_js('(function(){ ses.findById("wnd[0]/tbar[1]/btn[8]").press(); })()')
        pause("Executed — should see confirmation prompt")

        # Step 10b: Press Enter to confirm
        log.info("STEP 10b: Press Enter to confirm")
        ses.execute_js('(function(){ ses.findById("wnd[0]").sendVKey(0); })()')
        pause("Confirmed — check result screen")

        # Step 11: Scroll to bottom of result log
        log.info("STEP 11: Scroll to bottom of result log")
        scroll_info = ses.execute_js('''(function(){
            var usr = ses.findById("wnd[0]/usr");
            var scr = null;
            try { scr = usr.findById("lcnt").verticalScrollbar; } catch(e) {}
            if (!scr) try { scr = usr.verticalScrollbar; } catch(e) {}
            if (!scr) {
                try { scr = ses.findById("wnd[0]").verticalScrollbar; } catch(e) {}
            }
            if (scr) {
                var max = scr.maximum;
                scr.position = max;
                return "scrolled to " + max;
            }
            return "no scrollbar found";
        })()''')
        log.info("Scroll result: %s", scroll_info)
        pause("Scrolled to bottom")

        # Step 12: Read bottom lines
        log.info("STEP 12: Reading bottom lines...")
        bottom_text = ses.execute_js('''(function(){
            var lines = [];
            var usr = ses.findById("wnd[0]/usr");
            for (var r = 0; r < 30; r++) {
                try {
                    var txt = "" + usr.findById("lbl[0," + r + "]").text;
                    if (txt) lines.push(txt);
                } catch(e) { break; }
            }
            return lines.join("\\n");
        })()''')
        log.info("Bottom lines:\n%s", bottom_text)

        # Step 13: Read status bar
        log.info("STEP 13: Reading status bar...")
        sbar = ses.execute_js('(function(){ return "" + ses.findById("wnd[0]/sbar").text; })()')
        log.info("Status bar: %s", sbar)

        log.info("Pausing 10s so you can inspect the result screen...")
        time.sleep(10)

        log.info("DONE — leaving SAP open for you to inspect")

    except Exception as exc:
        log.error("FAILED at current step: %s", exc)
        log.info("Leaving SAP open for inspection")
        raise


if __name__ == "__main__":
    main()

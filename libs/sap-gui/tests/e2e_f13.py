"""E2E test: full F.13 automatic clearing flow (VPN → login → clear → check errors).

Requires:
    - SAP GUI running and connected to a system
    - Environment variables: SAP_USERNAME, SAP_PASSWORD
    - Optional: SAP_LANGUAGE (default: ZH)

Usage:
    uv run --project libs/sap-gui python libs/sap-gui/tests/e2e_f13.py
"""

from __future__ import annotations

import logging
import os
import sys
import time

from dotenv import load_dotenv
from vpn import ensure_vpn

from sap_gui.processes.f13 import run, previous_month_range

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    username = os.environ.get("SAP_USERNAME", "")
    password = os.environ.get("SAP_PASSWORD", "")
    language = os.environ.get("SAP_LANGUAGE", "ZH")

    if not username or not password:
        print("ERROR: Set SAP_USERNAME and SAP_PASSWORD environment variables")
        sys.exit(1)

    d_from, d_to = previous_month_range()

    log.info("Ensuring VPN is connected...")
    ensure_vpn()

    log.info("Starting F.13 E2E test")
    log.info("  User:         %s", username)
    log.info("  Company code: 9451")
    log.info("  Dates:        %s – %s", d_from, d_to)
    log.info("  GL account:   22029999")
    log.info("  Test run:     False (live clearing)")

    t0 = time.monotonic()

    result = run(
        username=username,
        password=password,
        company_code="9451",
        date_from=d_from,
        date_to=d_to,
        gl_account="22029999",
        test_run=False,
        language=language,
    )

    elapsed = time.monotonic() - t0

    log.info("=" * 60)
    log.info("E2E PASSED  %.1fs", elapsed)
    if result:
        log.info("Result:\n%s", result)


if __name__ == "__main__":
    main()

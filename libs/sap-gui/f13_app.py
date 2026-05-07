"""Standalone F.13 Automatic Clearing — entry point for PyInstaller build.

Usage:
    ./f13_clearing                           # previous month, live clearing
    ./f13_clearing --test                    # previous month, test mode
    ./f13_clearing --from 2026.01.01 --to 2026.01.31
    ./f13_clearing --company 9451 --gl 22029999
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv


def parse_date(s: str) -> date:
    """Parse YYYY.MM.DD or YYYY-MM-DD."""
    return date.fromisoformat(s.replace(".", "-"))


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="F.13 Automatic Clearing (自动清帐)")
    parser.add_argument("--company", default="9451", help="Company code (default: 9451)")
    parser.add_argument("--gl", default="22029999", help="GL account (default: 22029999)")
    parser.add_argument("--from", dest="date_from", type=parse_date, help="Start date (YYYY.MM.DD)")
    parser.add_argument("--to", dest="date_to", type=parse_date, help="End date (YYYY.MM.DD)")
    parser.add_argument("--year", type=int, help="Fiscal year (default: from date's year)")
    parser.add_argument("--test", action="store_true", help="Run in test mode (no actual clearing)")
    parser.add_argument("--no-vpn", action="store_true", help="Skip VPN check")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)

    username = os.environ.get("SAP_USERNAME", "")
    password = os.environ.get("SAP_PASSWORD", "")
    language = os.environ.get("SAP_LANGUAGE", "ZH")

    if not username or not password:
        print("ERROR: Set SAP_USERNAME and SAP_PASSWORD environment variables (or in .env)")
        sys.exit(1)

    # VPN
    if not args.no_vpn:
        log.info("Ensuring VPN is connected...")
        from vpn import ensure_vpn
        ensure_vpn()

    # Date range
    from sap_gui.processes.f13 import run, previous_month_range
    d_from, d_to = args.date_from, args.date_to
    if not d_from or not d_to:
        d_from, d_to = previous_month_range()

    log.info("F.13 Automatic Clearing")
    log.info("  Company:   %s", args.company)
    log.info("  GL:        %s", args.gl)
    log.info("  Dates:     %s – %s", d_from, d_to)
    log.info("  Test mode: %s", args.test)

    result = run(
        username=username,
        password=password,
        company_code=args.company,
        date_from=d_from,
        date_to=d_to,
        fiscal_year=args.year,
        gl_account=args.gl,
        test_run=args.test,
        language=language,
    )

    if result:
        print(result)


if __name__ == "__main__":
    main()

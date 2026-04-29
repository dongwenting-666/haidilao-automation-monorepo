"""Standalone ZFI0156 Store Actual Consumption Report — entry point for PyInstaller build.

Usage:
    ./zfi0156                                  # previous month, default plants
    ./zfi0156 --from 2026.02.01 --to 2026.02.28
    ./zfi0156 --plant-low CA01 --plant-high CA09
    ./zfi0156 --output ./output/sap/zfi0156-202602.xlsx
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv


def parse_date(s: str) -> date:
    """Parse YYYY.MM.DD or YYYY-MM-DD."""
    return date.fromisoformat(s.replace(".", "-"))


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="ZFI0156 Store Actual Consumption (门店实际耗用数据统计表)")
    parser.add_argument("--plant-low", default="CA01", help="Plant code low (default: CA01)")
    parser.add_argument("--plant-high", default="CA09", help="Plant code high (default: CA09)")
    parser.add_argument("--from", dest="date_from", type=parse_date, help="Start date (YYYY.MM.DD)")
    parser.add_argument("--to", dest="date_to", type=parse_date, help="End date (YYYY.MM.DD)")
    parser.add_argument("--output", type=Path, help="Output xlsx path (default: output/sap/zfi0156-{YYYYMM}.xlsx)")
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

    if not args.no_vpn:
        log.info("Ensuring VPN is connected...")
        from vpn import ensure_vpn
        ensure_vpn()

    from sap_gui.processes.zfi0156 import default_filename, previous_month_range, run

    d_from, d_to = args.date_from, args.date_to
    if not d_from or not d_to:
        d_from, d_to = previous_month_range()

    output = args.output
    if output is None:
        output = Path("output/sap") / default_filename(d_from)

    log.info("ZFI0156 Store Actual Consumption Report")
    log.info("  Plants:  %s - %s", args.plant_low, args.plant_high)
    log.info("  Dates:   %s – %s", d_from, d_to)
    log.info("  Output:  %s", output)

    result = run(
        username=username,
        password=password,
        output_path=output,
        plant_low=args.plant_low,
        plant_high=args.plant_high,
        date_from=d_from,
        date_to=d_to,
        language=language,
    )

    print(result)


if __name__ == "__main__":
    main()

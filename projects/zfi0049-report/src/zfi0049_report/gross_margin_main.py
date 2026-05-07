from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from vpn.connect import ensure_vpn
from zfi0049_report.gross_margin import generate_gross_margin_workbook
from zfi0049_report.main import (
    COMPANY_LABELS,
    DEFAULT_MAPPING_PATH,
    DEFAULT_OUTPUT_DIR,
    _execute_report,
)

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    today = date.today()
    default_period = today.month - 1 if today.month > 1 else 12
    default_year = today.year - 1 if today.month <= 3 else today.year

    parser = argparse.ArgumentParser(description="Export SAP ZFI0049 gross margin workbook")
    parser.add_argument("--company-code", required=True, choices=sorted(COMPANY_LABELS))
    parser.add_argument("--fiscal-year", type=int, default=default_year)
    parser.add_argument("--posting-period", type=int, default=default_period, choices=range(1, 13))
    parser.add_argument("--gl-low", default="50000000")
    parser.add_argument("--gl-high", default="69999999")
    parser.add_argument("--max-hits", type=int, default=10_000_000)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--language", default="ZH")
    parser.add_argument("--store-name", default="", help="Single store to export; empty means all stores")
    return parser.parse_args()


def main() -> Path:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    username = os.getenv("SAP_USERNAME", "")
    password = os.getenv("SAP_PASSWORD", "")
    if not username or not password:
        raise SystemExit("SAP_USERNAME and SAP_PASSWORD are required")

    log.info("Ensuring VPN is connected...")
    ensure_vpn()

    company_label = COMPANY_LABELS.get(args.company_code, args.company_code)
    output_dir = args.output_dir / f"{args.fiscal_year}-{args.posting_period:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    raw_output_path = output_dir / (
        f"zfi0049_gross_margin_raw_{args.company_code}_{company_label}_{args.fiscal_year}_{args.posting_period:02d}_{timestamp}.xlsx"
    )

    exported = _execute_report(
        username=username,
        password=password,
        company_code=args.company_code,
        fiscal_year=args.fiscal_year,
        posting_period=args.posting_period,
        gl_low=args.gl_low,
        gl_high=args.gl_high,
        max_hits=args.max_hits,
        output_path=raw_output_path,
        language=args.language,
    )
    log.info("Raw export saved to %s", exported)

    store_suffix = f"_{args.store_name}" if args.store_name else ""
    report_path = output_dir / (
        f"gross_margin_{args.company_code}_{args.fiscal_year}_{args.posting_period:02d}{store_suffix}_{timestamp}.xlsx"
    )
    generate_gross_margin_workbook(
        source_path=exported,
        mapping_path=args.mapping,
        output_path=report_path,
        store_name=args.store_name,
    )
    log.info("Report saved to %s", report_path)
    return report_path


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

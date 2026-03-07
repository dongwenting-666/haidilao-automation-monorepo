"""KSB1 Accounting Check - thin CLI wrapper."""

import argparse
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sap_gui.processes.ksb1 import DEFAULT_COST_CENTERS_FILE, previous_month_range, run

def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains .git)."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current

DEFAULT_OUTPUT_DIR = _find_repo_root() / "output"


def parse_args() -> argparse.Namespace:
    date_from, date_to = previous_month_range()

    parser = argparse.ArgumentParser(description="KSB1 monthly export automation")
    parser.add_argument(
        "--username",
        help="SAP username (or set SAP_USERNAME env var)",
    )
    parser.add_argument(
        "--password",
        help="SAP password (or set SAP_PASSWORD env var)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--date-from",
        type=date.fromisoformat,
        default=date_from,
        help=f"Start date YYYY-MM-DD (default: {date_from.isoformat()})",
    )
    parser.add_argument(
        "--date-to",
        type=date.fromisoformat,
        default=date_to,
        help=f"End date YYYY-MM-DD (default: {date_to.isoformat()})",
    )
    parser.add_argument(
        "--language",
        default="ZH",
        help="SAP logon language (default: ZH)",
    )
    return parser.parse_args()


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    username = args.username or os.getenv("SAP_USERNAME")
    password = args.password or os.getenv("SAP_PASSWORD")

    if not username or not password:
        raise SystemExit(
            "SAP credentials required. Use --username/--password or set SAP_USERNAME/SAP_PASSWORD in .env"
        )

    year_month = f"{args.date_from.year}-{args.date_from.month:02d}"
    output_path = args.output_dir / f"ksb1-{year_month}.XLSX"

    run(
        username=username,
        password=password,
        cost_center_file=DEFAULT_COST_CENTERS_FILE,
        output_path=output_path,
        date_from=args.date_from,
        date_to=args.date_to,
        language=args.language,
    )


if __name__ == "__main__":
    main()

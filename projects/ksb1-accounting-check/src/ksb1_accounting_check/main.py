"""KSB1 Accounting Check — download KSB1 and compare months by 科目 per store."""

import argparse
import calendar
import logging
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sap_gui.processes.ksb1 import DEFAULT_COST_CENTERS_FILE, run as ksb1_export

from ksb1_accounting_check.analyze import generate_report


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains .git)."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


DEFAULT_OUTPUT_DIR = _find_repo_root() / "output" / "ksb1"


def _prev_month_year() -> tuple[int, int]:
    """Return (previous_month, corresponding_year) relative to today."""
    today = date.today()
    if today.month == 1:
        return 12, today.year - 1
    return today.month - 1, today.year


def _month_range(year: int, month: int) -> tuple[date, date]:
    """Return (first_day_of_prev_month, last_day_of_month)."""
    if month == 1:
        prev_start = date(year - 1, 12, 1)
    else:
        prev_start = date(year, month - 1, 1)
    last_day = calendar.monthrange(year, month)[1]
    curr_end = date(year, month, last_day)
    return prev_start, curr_end


def parse_args() -> argparse.Namespace:
    default_month, default_year = _prev_month_year()

    parser = argparse.ArgumentParser(
        description="KSB1 accounting check: download and compare months by 科目 per store",
    )
    parser.add_argument(
        "month",
        type=int,
        nargs="?",
        default=default_month,
        help="Month to check (1-12, default: previous month)",
    )
    parser.add_argument(
        "year",
        type=int,
        nargs="?",
        default=default_year,
        help="Year (default: current year or previous year for Jan)",
    )
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
        "--skip-download",
        action="store_true",
        help="Skip SAP download, use existing KSB1 export file",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model for LLM-enhanced observations (e.g., qwen3:8b). Default: rules only.",
    )
    parser.add_argument(
        "--language",
        default="ZH",
        help="SAP logon language (default: ZH)",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    year, month = args.year, args.month
    date_from, date_to = _month_range(year, month)
    year_month = f"{year}-{month:02d}"

    output_dir = args.output_dir / year_month
    ksb1_path = output_dir / f"ksb1-{year_month}.XLSX"
    timestamp = datetime.now().strftime("%H%M%S")
    report_path = output_dir / f"{year_month}_KSB1_检查报告_{timestamp}.XLSX"

    # Step 1: Download KSB1 from SAP
    if not args.skip_download:
        username = args.username or os.getenv("SAP_USERNAME")
        password = args.password or os.getenv("SAP_PASSWORD")

        if not username or not password:
            raise SystemExit(
                "SAP credentials required. Use --username/--password "
                "or set SAP_USERNAME/SAP_PASSWORD in .env"
            )

        logging.info("Downloading KSB1 for %s (%s to %s)...", year_month, date_from, date_to)
        ksb1_export(
            username=username,
            password=password,
            cost_center_file=DEFAULT_COST_CENTERS_FILE,
            output_path=ksb1_path,
            date_from=date_from,
            date_to=date_to,
            language=args.language,
        )
    else:
        if not ksb1_path.exists():
            raise SystemExit(f"KSB1 file not found: {ksb1_path}")
        logging.info("Skipping download, using existing %s", ksb1_path)

    # Step 2: Generate comparison report
    logging.info("Generating accounting check report...")
    result = generate_report(
        ksb1_path=ksb1_path,
        output_path=report_path,
        target_month=month,
        model=args.model,
    )
    logging.info("Done! Report saved to %s", result)


if __name__ == "__main__":
    main()

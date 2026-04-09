"""Travel Expense Budget Report — 差旅费预算明细.

Downloads KSB1 (travel expenses) and QBI (store revenue) data,
then generates a budget report comparing actual vs allocated travel budget.

Data sources:
- KSB1: Previous year full + current year YTD → travel expenses by cost center
- QBI: Previous year full → store revenue
- DB: Current year target revenue per store (admin setting)

Usage:
    uv run --project projects/travel-expense-budget \
        python -m travel_expense_budget.main 3 2026

    # Skip downloads (use existing files):
    uv run --project projects/travel-expense-budget \
        python -m travel_expense_budget.main 3 2026 --skip-download
"""

from __future__ import annotations

import argparse
import calendar
import logging
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from travel_expense_budget.config import DEFAULT_CAD_TO_USD
from travel_expense_budget.extract import (
    extract_travel_expenses,
    extract_travel_from_multiple,
)
from travel_expense_budget.report import compute_report, generate_excel

log = logging.getLogger(__name__)


def _find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


REPO_ROOT = _find_repo_root()
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "travel-budget"
KSB1_OUTPUT_DIR = REPO_ROOT / "output" / "ksb1"


def _download_ksb1(
    date_from: date,
    date_to: date,
    output_path: Path,
    username: str,
    password: str,
    language: str,
) -> Path:
    """Download KSB1 data from SAP for the given date range."""
    from sap_gui.processes.ksb1 import DEFAULT_COST_CENTERS_FILE, run as ksb1_export
    from vpn.connect import ensure_vpn

    log.info("Ensuring VPN is connected...")
    ensure_vpn()

    log.info("Downloading KSB1 for %s to %s...", date_from, date_to)
    return ksb1_export(
        username=username,
        password=password,
        cost_center_file=DEFAULT_COST_CENTERS_FILE,
        output_path=output_path,
        date_from=date_from,
        date_to=date_to,
        language=language,
    )



def _find_ksb1_monthly_files(year: int, months: range) -> list[Path]:
    """Find existing monthly KSB1 download files."""
    files = []
    for m in months:
        ym = f"{year}-{m:02d}"
        path = KSB1_OUTPUT_DIR / ym / f"ksb1-{ym}.XLSX"
        if path.exists():
            files.append(path)
            log.info("Found existing KSB1: %s", path)
        else:
            log.warning("Missing KSB1 for %s: %s", ym, path)
    return files


def _load_from_db(year: int) -> tuple[dict[str, dict], float]:
    """Load all travel budget config from DB.

    Returns (db_data, cad_to_usd_rate) where db_data is
    {store_name: {target_revenue, prev_year_revenue, prev_year_travel, q1_revenue}}.
    """
    try:
        from server.db import get_travel_budget_targets

        data = get_travel_budget_targets(year)
        if not data:
            return {}, DEFAULT_CAD_TO_USD

        rate = next(iter(data.values()))["cad_to_usd_rate"]
        return data, rate
    except Exception as e:
        log.warning("Could not load from DB: %s", e)
        return {}, DEFAULT_CAD_TO_USD


def parse_args() -> argparse.Namespace:
    today = date.today()
    default_month = today.month - 1 if today.month > 1 else 12
    default_year = today.year if today.month > 1 else today.year - 1

    parser = argparse.ArgumentParser(
        description="Travel expense budget report (差旅费预算明细)",
    )
    parser.add_argument(
        "report_month",
        type=int,
        nargs="?",
        default=default_month,
        choices=range(1, 13),
        help="Report up to this month (1-12, default: previous month)",
    )
    parser.add_argument(
        "year",
        type=int,
        nargs="?",
        default=default_year,
        help="Current fiscal year (default: current or previous year)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip SAP download, use existing KSB1 files for YTD",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--language", default="ZH", help="SAP logon language")
    return parser.parse_args()


def main() -> Path:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()

    curr_year = args.year
    prev_year = curr_year - 1
    report_month = args.report_month

    username = os.getenv("SAP_USERNAME", "")
    password = os.getenv("SAP_PASSWORD", "")

    output_dir = args.output_dir / f"{curr_year}-{report_month:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    report_path = output_dir / f"travel_budget_{curr_year}_{report_month:02d}_{timestamp}.xlsx"

    # ── 0. Load DB config ────────────────────────────────────────────────
    db_data, curr_rate = _load_from_db(curr_year)
    if not db_data:
        raise SystemExit(
            "No travel budget targets configured for %d. "
            "Set targets in admin panel at /admin/travel-budget" % curr_year
        )
    log.info("Loaded DB config: %d stores, rate=%.6f", len(db_data), curr_rate)

    # ── 1. Current year YTD travel expenses (KSB1) ───────────────────────
    if args.skip_download:
        files = _find_ksb1_monthly_files(curr_year, range(1, report_month + 1))
        full_path = output_dir / f"ksb1-{curr_year}-ytd.XLSX"
        if full_path.exists():
            curr_travel = extract_travel_expenses(full_path, cad_to_usd=curr_rate)
        elif files:
            curr_travel = extract_travel_from_multiple(files, cad_to_usd=curr_rate)
        else:
            log.warning("No KSB1 files for %d YTD — using zeros", curr_year)
            curr_travel = {}
    else:
        curr_ksb1_path = output_dir / f"ksb1-{curr_year}-ytd.XLSX"
        last_day = calendar.monthrange(curr_year, report_month)[1]
        _download_ksb1(
            date_from=date(curr_year, 1, 1),
            date_to=date(curr_year, report_month, last_day),
            output_path=curr_ksb1_path,
            username=username,
            password=password,
            language=args.language,
        )
        curr_travel = extract_travel_expenses(curr_ksb1_path, cad_to_usd=curr_rate)

    # ── 2. Compute and generate ──────────────────────────────────────────
    log.info("Computing report for %d up to month %d...", curr_year, report_month)
    rows = compute_report(
        curr_year_travel=curr_travel,
        db_data=db_data,
        report_month=report_month,
        prev_year=prev_year,
        curr_year=curr_year,
    )

    result = generate_excel(
        rows=rows,
        output_path=report_path,
        report_month=report_month,
        prev_year=prev_year,
        curr_year=curr_year,
    )

    # Print summary
    log.info("\n=== Travel Budget Summary (%d, up to month %d) ===", curr_year, report_month)
    for r in rows:
        log.info(
            "  %-28s q1_budget=%10.2f  full_budget=%10.2f  ytd=%10.2f",
            r.name, r.q1_budget, r.full_year_budget, r.ytd_actual,
        )

    return result


if __name__ == "__main__":
    main()

"""CLI entry point for the daily store operation report."""

from __future__ import annotations

import argparse
import functools
import io
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from daily_store_operation_report.dates import compute_dates
from daily_store_operation_report.download import DownloadedFiles, download_all
from daily_store_operation_report.report import generate_report
from daily_store_operation_report.transform import compute_metrics
from daily_store_operation_report.validation import (
    validate_file_exists_and_readable,
    validate_file_timestamps,
    validate_report_output,
    validate_xlsx_has_sheet,
)
from vpn.connect import ensure_vpn

logger = logging.getLogger(__name__)

_ALERT_CHAT_ID = "oc_ff2a74b2ba7b07eee95c6138b9cfd112"


@functools.cache
def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains pyproject.toml with workspace)."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        toml = p / "pyproject.toml"
        if toml.exists() and "[tool.uv.workspace]" in toml.read_text(encoding="utf-8"):
            return p
        p = p.parent
    return Path.cwd()


def _date_from_filename(p: Path) -> str:
    """Extract a download-timestamp sort key from a QBI filename.

    QBI exports are named with a download timestamp, e.g.:
        海外门店经营日报数据_20260319_2001.xlsx      → '20260319_2001'
        海外门店经营日报数据_20260319_2002_2.xlsx    → '20260319_2002_2'
        海外分时段报表_20260319_2003.xlsx            → '20260319_2003'

    We strip the Chinese prefix (everything before the first numeric segment)
    and return the remaining underscore-joined parts so that:
      - Files from different download sessions sort by download date+time.
      - The ``_2`` duplicate-avoidance suffix sorts naturally after the
        same timestamp without the suffix.

    Falls back to the full stem if the stem has fewer than 2 underscore-split
    parts after stripping the prefix.
    """
    parts = p.stem.split("_")
    # Drop leading non-numeric prefix parts (the Chinese report name)
    numeric_start = next((i for i, part in enumerate(parts) if part.isdigit()), None)
    if numeric_start is not None and numeric_start < len(parts) - 1:
        return "_".join(parts[numeric_start:])
    return p.stem


def _resolve_data_files(data_dir: Path) -> DownloadedFiles:
    """Find the 5 QBI files in a directory by matching filenames.

    Files are sorted by their download timestamp (embedded in the filename).
    Within each download session the 3 daily files are downloaded in order:
      1. current month  (earliest timestamp → sorts to [-3])
      2. previous month (middle timestamp  → sorts to [-2])
      3. previous year  (latest timestamp  → sorts to [-1])

    Similarly the 2 time-period files are downloaded as:
      1. current month  (earlier timestamp → sorts to [-2])
      2. previous year  (later timestamp   → sorts to [-1])

    For precise control over which files are used, pass explicit paths via
    --cur-daily, --prev-daily, --yoy-daily, --cur-tp, --yoy-tp instead.
    """
    # Compute sort keys so we can log them for transparency
    daily_unsorted = list(data_dir.glob("海外门店经营日报数据_*.xlsx"))
    tp_unsorted = list(data_dir.glob("海外分时段报表_*.xlsx"))

    daily_with_keys = [(p, _date_from_filename(p)) for p in daily_unsorted]
    tp_with_keys = [(p, _date_from_filename(p)) for p in tp_unsorted]

    daily_with_keys.sort(key=lambda x: x[1])
    tp_with_keys.sort(key=lambda x: x[1])

    daily_files = [p for p, _ in daily_with_keys]
    tp_files = [p for p, _ in tp_with_keys]

    if len(daily_files) < 3:
        raise FileNotFoundError(
            f"Need at least 3 daily report files in {data_dir}, found {len(daily_files)}.\n"
            f"  Files found: {[p.name for p in daily_files]}"
        )
    if len(tp_files) < 2:
        raise FileNotFoundError(
            f"Need at least 2 time-period report files in {data_dir}, found {len(tp_files)}.\n"
            f"  Files found: {[p.name for p in tp_files]}"
        )

    # Log the sort keys so the user can verify the ordering
    logger.info("Daily files resolved (sorted by sort key):")
    for p, key in daily_with_keys:
        logger.info("  sort_key=%-20s  file=%s", key, p.name)

    logger.info("Time-period files resolved (sorted by sort key):")
    for p, key in tp_with_keys:
        logger.info("  sort_key=%-20s  file=%s", key, p.name)

    files = DownloadedFiles(
        cur_daily=daily_files[-3],
        prev_daily=daily_files[-2],
        yoy_daily=daily_files[-1],
        cur_time_period=tp_files[-2],
        yoy_time_period=tp_files[-1],
    )
    logger.info(
        "Selected data files: cur=%s, prev=%s, yoy=%s, cur_tp=%s, yoy_tp=%s",
        files.cur_daily.name,
        files.prev_daily.name,
        files.yoy_daily.name,
        files.cur_time_period.name,
        files.yoy_time_period.name,
    )

    # Validate that all 5 selected files are from the same download session
    selected_with_keys = [
        (files.cur_daily, _date_from_filename(files.cur_daily)),
        (files.prev_daily, _date_from_filename(files.prev_daily)),
        (files.yoy_daily, _date_from_filename(files.yoy_daily)),
        (files.cur_time_period, _date_from_filename(files.cur_time_period)),
        (files.yoy_time_period, _date_from_filename(files.yoy_time_period)),
    ]
    validate_file_timestamps(selected_with_keys)

    return files


def _lark_alert(message: str) -> None:
    """Send a Lark text alert to the config group. Best-effort — never raises."""
    try:
        app_id = os.environ.get("LARK_APP_ID", "")
        app_secret = os.environ.get("LARK_APP_SECRET", "")
        if not app_id or not app_secret:
            logger.warning("LARK_APP_ID/SECRET not set — skipping Lark alert")
            return
        from lark_client import LarkClient
        with LarkClient(app_id=app_id, app_secret=app_secret) as client:
            client.send_text(message, chat_id=_ALERT_CHAT_ID)
        logger.info("Lark alert sent to %s", _ALERT_CHAT_ID)
    except Exception:
        logger.exception("Failed to send Lark alert")


def _check_config(month_key: str) -> None:
    """Check that targets and competitor config are in the DB for *month_key*.

    If either is missing, sends a Lark alert and raises SystemExit to abort.
    """
    try:
        from server.db import has_competitors, has_targets, is_db_available
    except ImportError:
        logger.error(
            "Cannot import server.db — ensure DATABASE_URL is set and the "
            "server package is installed (run from the monorepo root with uv)."
        )
        _lark_alert(f"⚠️ 日报生成失败\n\n无法导入数据库模块，请检查运行环境。")
        sys.exit(1)

    missing: list[str] = []

    if not is_db_available():
        missing.append("数据库未连接 — 请检查 DATABASE_URL 环境变量")
    else:
        if not has_targets(month_key):
            missing.append(f"数据库中缺少 {month_key} 的目标数据，请前往 /admin/targets 配置")
        if not has_competitors():
            missing.append("数据库中缺少假想敌配置，请前往 /admin/competitors 配置")

    if missing:
        items = "\n".join(f"• {m}" for m in missing)
        message = (
            f"⚠️ 日报生成失败 — 配置缺失 ({month_key})\n\n"
            f"{items}\n\n"
            "请前往管理后台更新配置：https://haidilao.wanghongming.xyz/admin"
        )
        logger.error("Config missing for %s:\n%s", month_key, items)
        _lark_alert(message)
        sys.exit(1)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate daily store operation report from QBI data",
    )
    parser.add_argument(
        "date",
        nargs="?",
        default=None,
        help="Report date in YYYY-MM-DD format (default: yesterday)",
    )
    parser.add_argument("--skip-download", action="store_true", help="Use pre-downloaded files")
    parser.add_argument("--data-dir", type=Path, help="Directory with QBI export files")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", dest="headless", action="store_false")

    # Explicit file paths for --skip-download
    parser.add_argument("--cur-daily", type=Path, help="Current month daily report file")
    parser.add_argument("--prev-daily", type=Path, help="Previous month daily report file")
    parser.add_argument("--yoy-daily", type=Path, help="Previous year daily report file")
    parser.add_argument("--cur-tp", type=Path, help="Current month time-period report file")
    parser.add_argument("--yoy-tp", type=Path, help="Previous year time-period report file")
    args = parser.parse_args()

    # Force UTF-8 output on Windows to handle Chinese characters
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Resolve report date
    if args.date:
        report_date = date.fromisoformat(args.date)
    else:
        report_date = date.today() - timedelta(days=1)

    dates = compute_dates(report_date)
    logger.info("Report date: %s (%s)", report_date, dates.month_key)

    # Check that targets and competitor config exist for the current month.
    # If missing, send a Lark alert and abort.
    _check_config(dates.month_key)

    # Resolve output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = _find_repo_root() / "output" / "daily-report"

    # Resolve data files
    has_explicit = any((args.cur_daily, args.prev_daily, args.yoy_daily, args.cur_tp, args.yoy_tp))

    if has_explicit:
        # All 5 must be provided when using explicit paths
        missing = []
        for name in ("cur_daily", "prev_daily", "yoy_daily", "cur_tp", "yoy_tp"):
            if getattr(args, name) is None:
                missing.append(f"--{name.replace('_', '-')}")
        if missing:
            parser.error(f"When providing explicit files, all 5 are required. Missing: {', '.join(missing)}")
        files = DownloadedFiles(
            cur_daily=args.cur_daily,
            prev_daily=args.prev_daily,
            yoy_daily=args.yoy_daily,
            cur_time_period=args.cur_tp,
            yoy_time_period=args.yoy_tp,
        )
    elif args.skip_download:
        data_dir = args.data_dir or _find_repo_root() / "output" / "qbi"
        logger.info("Using pre-downloaded files from %s", data_dir)
        files = _resolve_data_files(data_dir)
    else:
        username = os.environ.get("QBI_USERNAME", "")
        password = os.environ.get("QBI_PASSWORD", "")
        if not username or not password:
            logger.error("QBI_USERNAME and QBI_PASSWORD environment variables required")
            sys.exit(1)
        logger.info("Ensuring VPN is connected...")
        ensure_vpn()

        data_dir = args.data_dir or _find_repo_root() / "output" / "qbi"
        files = download_all(
            dates,
            username=username,
            password=password,
            download_dir=data_dir,
            headless=args.headless,
        )

    # Validate all 5 input files before doing any work
    logger.info("Validating input files...")
    from daily_store_operation_report.constants import QBI_SHEET_DAILY, QBI_SHEET_TIME_PERIOD
    file_checks = [
        (files.cur_daily, "cur_daily", QBI_SHEET_DAILY),
        (files.prev_daily, "prev_daily", QBI_SHEET_DAILY),
        (files.yoy_daily, "yoy_daily", QBI_SHEET_DAILY),
        (files.cur_time_period, "cur_time_period", QBI_SHEET_TIME_PERIOD),
        (files.yoy_time_period, "yoy_time_period", QBI_SHEET_TIME_PERIOD),
    ]
    for path, label, expected_sheet in file_checks:
        validate_file_exists_and_readable(path, label=label)
        validate_xlsx_has_sheet(path, expected_sheet)
    logger.info("Input file validation passed ✓")

    logger.info("Computing metrics...")
    report_data = compute_metrics(dates, files)

    logger.info("Generating report...")
    output_path = generate_report(report_data, output_dir)
    logger.info("Report saved to %s", output_path)

    # Post-generation self-test
    logger.info("Running post-generation self-test...")
    try:
        validate_report_output(output_path)
    except ValueError as exc:
        logger.error("Post-generation validation FAILED: %s", exc)
        _lark_alert(f"⚠️ 日报自检失败 ({dates.month_key})\n\n{exc}")
        # Don't abort — the file was saved; let the human inspect it
    except Exception as exc:
        logger.warning("Post-generation validation raised unexpected error: %s", exc)


if __name__ == "__main__":
    main()

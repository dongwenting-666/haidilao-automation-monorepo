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
    """Extract date range string from QBI filename for sorting.

    Filenames look like: 海外门店经营日报数据_20260201_20260210.xlsx
    Returns the end date portion (e.g. '20260210') for sorting.
    Falls back to stem if pattern doesn't match.
    """
    parts = p.stem.split("_")
    return parts[-1] if len(parts) >= 3 else p.stem


def _resolve_data_files(data_dir: Path) -> DownloadedFiles:
    """Find the 5 QBI files in a directory by matching filenames.

    Sorts by date extracted from filename (not mtime) so download order
    doesn't matter. The file with the latest end date is assumed to be
    the current month, second latest is previous month, third is YoY.
    For precise control, use --cur-daily, --prev-daily, etc. instead.
    """
    daily_files = sorted(data_dir.glob("海外门店经营日报数据_*.xlsx"), key=_date_from_filename)
    tp_files = sorted(data_dir.glob("海外分时段报表_*.xlsx"), key=_date_from_filename)

    if len(daily_files) < 3:
        raise FileNotFoundError(
            f"Need at least 3 daily report files in {data_dir}, found {len(daily_files)}"
        )
    if len(tp_files) < 2:
        raise FileNotFoundError(
            f"Need at least 2 time-period report files in {data_dir}, found {len(tp_files)}"
        )

    files = DownloadedFiles(
        cur_daily=daily_files[-1],
        prev_daily=daily_files[-2],
        yoy_daily=daily_files[-3],
        cur_time_period=tp_files[-1],
        yoy_time_period=tp_files[-2],
    )
    logger.info(
        "Resolved data files: cur=%s, prev=%s, yoy=%s, cur_tp=%s, yoy_tp=%s",
        files.cur_daily.name,
        files.prev_daily.name,
        files.yoy_daily.name,
        files.cur_time_period.name,
        files.yoy_time_period.name,
    )
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
    from server.db import has_competitors, has_targets, is_db_available

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

    logger.info("Computing metrics...")
    report_data = compute_metrics(dates, files)

    logger.info("Generating report...")
    output_path = generate_report(report_data, output_dir)
    logger.info("Report saved to %s", output_path)


if __name__ == "__main__":
    main()

"""QBI download orchestration — downloads 5 files for the report."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from qbi_crawler import QBISession, download_report, REPORT_DAILY, REPORT_TIME_PERIOD

from daily_store_operation_report.dates import ReportDates

logger = logging.getLogger(__name__)


@dataclass
class DownloadedFiles:
    """Paths to the 5 downloaded QBI files."""

    cur_daily: Path
    prev_daily: Path
    prev_full_daily: Path
    yoy_daily: Path
    cur_time_period: Path
    yoy_time_period: Path


def download_all(
    dates: ReportDates,
    *,
    username: str,
    password: str,
    download_dir: Path,
    headless: bool = True,
) -> DownloadedFiles:
    """Download all 5 QBI reports using a single browser session."""
    download_dir.mkdir(parents=True, exist_ok=True)

    # Extend YoY end date to include the same-weekday date (52 weeks back)
    # e.g. for report_date 2026-02-10, yoy_end=2025-02-10 but same_weekday=2025-02-11
    yoy_end_extended = max(dates.yoy_end, dates.yoy_same_weekday)

    with QBISession(username, password, headless=headless, timeout_ms=60_000) as session:
        page = session.page

        logger.info("Downloading current month daily report...")
        cur_daily = download_report(
            page, REPORT_DAILY,
            start_date=dates.cur_start.isoformat(),
            end_date=dates.cur_end.isoformat(),
            download_dir=download_dir,
        )

        logger.info("Downloading previous month daily report...")
        prev_daily = download_report(
            page, REPORT_DAILY,
            start_date=dates.prev_start.isoformat(),
            end_date=dates.prev_end.isoformat(),
            download_dir=download_dir,
        )

        logger.info("Downloading previous month full daily report...")
        prev_full_daily = download_report(
            page, REPORT_DAILY,
            start_date=dates.prev_start.isoformat(),
            end_date=dates.prev_full_end.isoformat(),
            download_dir=download_dir,
        )

        logger.info("Downloading YoY daily report...")
        yoy_daily = download_report(
            page, REPORT_DAILY,
            start_date=dates.yoy_start.isoformat(),
            end_date=yoy_end_extended.isoformat(),
            download_dir=download_dir,
        )

        logger.info("Downloading current month time-period report...")
        cur_tp = download_report(
            page, REPORT_TIME_PERIOD,
            start_date=dates.cur_start.isoformat(),
            end_date=dates.cur_end.isoformat(),
            download_dir=download_dir,
        )

        logger.info("Downloading YoY time-period report...")
        yoy_tp = download_report(
            page, REPORT_TIME_PERIOD,
            start_date=dates.yoy_start.isoformat(),
            end_date=yoy_end_extended.isoformat(),
            download_dir=download_dir,
        )

    return DownloadedFiles(
        cur_daily=cur_daily,
        prev_daily=prev_daily,
        prev_full_daily=prev_full_daily,
        yoy_daily=yoy_daily,
        cur_time_period=cur_tp,
        yoy_time_period=yoy_tp,
    )

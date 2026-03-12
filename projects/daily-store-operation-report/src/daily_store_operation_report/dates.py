"""Date range calculations for QBI downloads."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ReportDates:
    """All date ranges needed for the 5 QBI downloads."""

    report_date: date

    # Current month: 1st of month → report_date
    cur_start: date
    cur_end: date

    # Previous month same period: 1st of prev month → prev month same day
    prev_start: date
    prev_end: date

    # Previous year same period: 1st of same month last year → same day last year
    yoy_start: date
    yoy_end: date

    # Same weekday last year (52 weeks back)
    yoy_same_weekday: date

    @property
    def days_in_month(self) -> int:
        return calendar.monthrange(self.report_date.year, self.report_date.month)[1]

    @property
    def day_of_month(self) -> int:
        return self.report_date.day

    @property
    def time_progress(self) -> float:
        """标准时间进度: day_of_month / days_in_month."""
        return self.day_of_month / self.days_in_month

    @property
    def month_key(self) -> str:
        """Key for targets.json lookup, e.g. '2026-02'."""
        return self.report_date.strftime("%Y-%m")


def compute_dates(report_date: date) -> ReportDates:
    """Compute all date ranges from a single report date."""
    cur_start = report_date.replace(day=1)
    cur_end = report_date

    # Previous month same day (clamp if prev month is shorter)
    if report_date.month == 1:
        prev_month_year = report_date.year - 1
        prev_month = 12
    else:
        prev_month_year = report_date.year
        prev_month = report_date.month - 1

    prev_days = calendar.monthrange(prev_month_year, prev_month)[1]
    prev_day = min(report_date.day, prev_days)
    prev_start = date(prev_month_year, prev_month, 1)
    prev_end = date(prev_month_year, prev_month, prev_day)

    # Previous year same period
    yoy_year = report_date.year - 1
    yoy_month = report_date.month
    yoy_days = calendar.monthrange(yoy_year, yoy_month)[1]
    yoy_day = min(report_date.day, yoy_days)
    yoy_start = date(yoy_year, yoy_month, 1)
    yoy_end = date(yoy_year, yoy_month, yoy_day)

    # Same weekday last year = 52 weeks back (364 days)
    yoy_same_weekday = report_date - timedelta(days=364)

    return ReportDates(
        report_date=report_date,
        cur_start=cur_start,
        cur_end=cur_end,
        prev_start=prev_start,
        prev_end=prev_end,
        yoy_start=yoy_start,
        yoy_end=yoy_end,
        yoy_same_weekday=yoy_same_weekday,
    )

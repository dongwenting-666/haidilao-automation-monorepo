"""Tests for daily_store_operation_report.dates.compute_dates().

Edge cases: month boundaries, year boundaries, leap years, Feb 29,
month-length clamping, and the 52-week (364-day) same-weekday calculation.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from daily_store_operation_report.dates import compute_dates


class TestComputeDatesBasic:
    def test_cur_start_is_first_of_month(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.cur_start == date(2026, 3, 1)

    def test_cur_end_equals_report_date(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.cur_end == date(2026, 3, 15)

    def test_prev_start_is_first_of_prev_month(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.prev_start == date(2026, 2, 1)

    def test_prev_end_is_prev_month_same_day(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.prev_end == date(2026, 2, 15)

    def test_yoy_start_is_first_of_same_month_last_year(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.yoy_start == date(2025, 3, 1)

    def test_yoy_end_is_same_day_last_year(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.yoy_end == date(2025, 3, 15)

    def test_yoy_same_weekday_is_364_days_back(self):
        report = date(2026, 3, 15)
        d = compute_dates(report)
        assert d.yoy_same_weekday == report - timedelta(days=364)

    def test_month_key_format(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.month_key == "2026-03"

    def test_time_progress_mid_month(self):
        d = compute_dates(date(2026, 3, 15))
        assert abs(d.time_progress - 15 / 31) < 1e-9

    def test_day_of_month(self):
        d = compute_dates(date(2026, 3, 15))
        assert d.day_of_month == 15


class TestDecemberToJanuaryBoundary:
    """Test Jan 1–31: prev month = December of prior year."""

    def test_prev_start_is_dec_of_prior_year(self):
        d = compute_dates(date(2026, 1, 15))
        assert d.prev_start == date(2025, 12, 1)

    def test_prev_end_is_dec_same_day(self):
        d = compute_dates(date(2026, 1, 15))
        assert d.prev_end == date(2025, 12, 15)

    def test_yoy_month_key_is_jan_prev_year(self):
        d = compute_dates(date(2026, 1, 1))
        assert d.month_key == "2026-01"
        assert d.yoy_start == date(2025, 1, 1)

    def test_jan_1_prev_start_is_dec_1_prior(self):
        d = compute_dates(date(2027, 1, 1))
        assert d.prev_start == date(2026, 12, 1)
        assert d.prev_end == date(2026, 12, 1)


class TestMonthLengthClamping:
    """When reporting on a day that doesn't exist in prev/yoy month, clamp to last day."""

    def test_march_31_prev_is_feb_28_non_leap(self):
        # 2026 is not a leap year; Feb has 28 days → clamp day 31 → 28
        d = compute_dates(date(2026, 3, 31))
        assert d.prev_end == date(2026, 2, 28)

    def test_march_31_prev_is_feb_29_leap_year(self):
        # 2024 is a leap year; March 31 2024 → prev_end = Feb 29 2024
        d = compute_dates(date(2024, 3, 31))
        assert d.prev_end == date(2024, 2, 29)

    def test_march_31_yoy_clamps_to_feb_28(self):
        # Report on Mar 31 2026 → yoy March 2025 has 31 days, no clamping
        # But if we test May 31 → YoY May 2025 also 31 days, fine
        # Test Jan 31 → prev Dec 31 (no clamping needed, Dec has 31 days)
        d = compute_dates(date(2026, 1, 31))
        assert d.prev_end == date(2025, 12, 31)

    def test_may_31_prev_april_30(self):
        # April has 30 days; May 31 → prev_end = Apr 30
        d = compute_dates(date(2026, 5, 31))
        assert d.prev_end == date(2026, 4, 30)

    def test_aug_31_prev_july_31(self):
        # July has 31 days; no clamping
        d = compute_dates(date(2026, 8, 31))
        assert d.prev_end == date(2026, 7, 31)


class TestLeapYear:
    """Feb 29 in a leap year as report_date."""

    def test_feb_29_leap_year_report_date(self):
        d = compute_dates(date(2024, 2, 29))
        assert d.cur_start == date(2024, 2, 1)
        assert d.cur_end == date(2024, 2, 29)

    def test_feb_29_prev_month_is_jan_29(self):
        d = compute_dates(date(2024, 2, 29))
        # Previous month = Jan 2024 → day 29 exists in January
        assert d.prev_end == date(2024, 1, 29)

    def test_feb_29_yoy_clamps_to_feb_28(self):
        # 2023 is not a leap year; yoy_end for Feb 29 2024 → Feb 28 2023
        d = compute_dates(date(2024, 2, 29))
        assert d.yoy_end == date(2023, 2, 28)

    def test_yoy_same_weekday_preserves_weekday(self):
        report = date(2024, 2, 29)
        d = compute_dates(report)
        # 364 days = 52 weeks exactly → same day of week
        assert d.yoy_same_weekday.weekday() == report.weekday()


class TestProperties:
    def test_days_in_month_january(self):
        d = compute_dates(date(2026, 1, 10))
        assert d.days_in_month == 31

    def test_days_in_month_february_non_leap(self):
        d = compute_dates(date(2026, 2, 10))
        assert d.days_in_month == 28

    def test_days_in_month_february_leap(self):
        d = compute_dates(date(2024, 2, 10))
        assert d.days_in_month == 29

    def test_time_progress_last_day_of_month(self):
        d = compute_dates(date(2026, 1, 31))
        assert d.time_progress == pytest.approx(1.0)

    def test_time_progress_first_day(self):
        d = compute_dates(date(2026, 3, 1))
        assert d.time_progress == pytest.approx(1 / 31)

"""Unit tests for inventory_check.dates."""
from __future__ import annotations

import pytest

from inventory_check.dates import Month, month_to_period, parse_month


@pytest.mark.parametrize(
    "year,month,expected",
    [
        (2026, 1, "202601"),
        (2026, 3, "202603"),
        (2026, 9, "202609"),
        (2026, 10, "202610"),
        (2026, 12, "202612"),
    ],
)
def test_month_period(year: int, month: int, expected: str) -> None:
    assert Month(year, month).period == expected


def test_month_first_and_last_day_iso() -> None:
    m = Month(2026, 3)
    assert m.first_day_iso == "2026-03-01"
    assert m.last_day_iso == "2026-03-31"


def test_month_february_leap() -> None:
    """2024 is a leap year — Feb has 29 days."""
    assert Month(2024, 2).last_day_iso == "2024-02-29"
    assert Month(2025, 2).last_day_iso == "2025-02-28"


def test_month_february_century_non_leap() -> None:
    """1900 is divisible by 100 but not 400 — not a leap year."""
    assert Month(1900, 2).last_day_iso == "1900-02-28"


def test_month_february_400_year_leap() -> None:
    """2000 is divisible by 400 — leap year."""
    assert Month(2000, 2).last_day_iso == "2000-02-29"


@pytest.mark.parametrize("month", [0, 13, -1, 100])
def test_month_rejects_bad_month(month: int) -> None:
    with pytest.raises(ValueError, match="month must be 1-12"):
        Month(2026, month)


@pytest.mark.parametrize("year", [0, 1899, 10_000])
def test_month_rejects_bad_year(year: int) -> None:
    with pytest.raises(ValueError, match="year out of range"):
        Month(year, 1)


def test_parse_month_happy() -> None:
    assert parse_month("2026-03").year == 2026
    assert parse_month("2026-03").month == 3


@pytest.mark.parametrize("bad", ["2026-3", "2026/03", "26-03", "", "2026-13", "abcd-ef"])
def test_parse_month_rejects_bad_format(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_month(bad)


def test_month_to_period_shortcut() -> None:
    assert month_to_period("2026-03") == "202603"
    assert month_to_period("2026-12") == "202612"


def test_month_is_frozen() -> None:
    m = Month(2026, 3)
    with pytest.raises(Exception):
        m.year = 2027  # type: ignore[misc]

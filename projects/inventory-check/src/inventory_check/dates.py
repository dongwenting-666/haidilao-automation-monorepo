"""Date helpers for inventory-check.

Pure functions only — no I/O — so the test suite can run without
network or browser.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"month must be 1-12, got {self.month}")
        if not 1900 <= self.year <= 9999:
            raise ValueError(f"year out of range: {self.year}")

    @property
    def period(self) -> str:
        """SAP YYYYMM zero-padded period.

        >>> Month(2026, 3).period
        '202603'
        """
        return f"{self.year:04d}{self.month:02d}"

    @property
    def first_day_iso(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-01"

    @property
    def last_day_iso(self) -> str:
        from calendar import monthrange

        last = monthrange(self.year, self.month)[1]
        return f"{self.year:04d}-{self.month:02d}-{last:02d}"


def parse_month(s: str) -> Month:
    """Parse ``YYYY-MM`` (e.g. ``"2026-03"``) into a Month.

    >>> parse_month("2026-03").period
    '202603'
    """
    if len(s) != 7 or s[4] != "-":
        raise ValueError(f"month must be YYYY-MM, got {s!r}")
    try:
        y, m = int(s[:4]), int(s[5:])
    except ValueError as exc:
        raise ValueError(f"month must be YYYY-MM, got {s!r}") from exc
    return Month(y, m)


def month_to_period(s: str) -> str:
    """Shortcut: ``"2026-03"`` → ``"202603"``."""
    return parse_month(s).period

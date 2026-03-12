"""Shared utility functions for the daily store operation report."""

from __future__ import annotations


def div_or_zero(a: float, b: float) -> float:
    """Divide a by b, returning 0 when b is 0."""
    return a / b if b != 0 else 0.0


def comp_text(diff: float, unit: str = "桌") -> str:
    """Generate comparison text like '下降295.20桌', '上升10.50桌', or '持平'."""
    if diff < 0:
        return f"下降{abs(diff):.2f}{unit}"
    if diff > 0:
        return f"上升{diff:.2f}{unit}"
    return "持平"


def pct_str(v: float, decimals: int = 2) -> str:
    """Format as percentage string like '24.18%' or '-0.1%'."""
    return f"{v:.{decimals}f}%"

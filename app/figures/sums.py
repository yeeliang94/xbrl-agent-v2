"""The arithmetic shared by the figure store, the totals and the checks.

One place for: what a saved figure counts as (a blank or not-disclosed
figure counts as nothing, never zero), adding up a total's lines, and how
an amount is written in a sentence.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

CENT = 0.01


def money(value: float) -> float:
    return round(float(value), 2)


def known_value(value: Optional[float], status: Optional[str]) -> Optional[float]:
    """A figure's number, or None when it is blank or marked not disclosed."""
    if value is None or status == "not_disclosed":
        return None
    return float(value)


def add_up(children: Iterable[tuple[str, float]],
           value_of: Callable[[str], Optional[float]]) -> Optional[float]:
    """What a total's lines add up to (coefficient times value), rounded to cents.

    Blank lines count as zero once at least one line has a number. With no
    numeric line at all the answer is None, never zero."""
    total, numeric = 0.0, False
    for child, coefficient in children:
        value = value_of(child)
        if value is None:
            continue
        numeric = True
        total += float(coefficient) * float(value)
    return money(total) if numeric else None


def fmt_amount(value: float) -> str:
    """An amount as a sentence shows it: 1,250 or 1,250.50."""
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"

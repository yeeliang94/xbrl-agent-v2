"""The hard stops: the only writes the figure store refuses.

Used by `store.py` and nowhere else. These are the eight that
`docs/agent-lessons.md` section 7 recommends as hard stops in code, for
writes that would corrupt a filing, plus a ninth the owner added: a figure
a person typed into the workbook is kept fixed against agents. Two input
checks sit beside them (a value that is not a number, an overlong label).
Each returns one plain sentence the caller can act on, or None. Anything
merely unusual is accepted and can be flagged; it is not refused here.

Rules 4 and 5 judge an agent's evidence. A person's own edit is the
authority, so those two do not apply to it. The others apply to everyone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from app.figures.sums import CENT, fmt_amount


@dataclass(frozen=True)
class Line:
    """One printed line behind a figure."""
    printed_label: str
    page: int
    amount: Optional[float] = None
    print_order: int = 0
    coefficient: float = 1.0
    section: str = ""


def heading(label: str, kind: str) -> Optional[str]:
    """1. A value in a heading row."""
    if kind == "ABSTRACT":
        return f"{label} is a heading and cannot hold a value, so save the figure on a line under it."
    return None


def calculated_total(label: str, is_total: bool, total: Optional[str]) -> Optional[str]:
    """2. Overwriting a calculated total with a typed value."""
    if is_total and total is None:
        return (f"{label} is added up from the lines under it, so save those lines, "
                "or save this total as printed or as a total with no breakdown.")
    return None


def total_without_parts_agreeing(label: str, total: Optional[str], value: Optional[float],
                                 parts_sum: Optional[float]) -> Optional[str]:
    """3. A total typed as having no breakdown while its saved lines add to another amount."""
    if total == "no_breakdown" and value is not None and parts_sum is not None \
            and abs(parts_sum - value) > CENT:
        return (f"The lines under {label} already add up to {fmt_amount(parts_sum)}, so correct "
                "or clear them before saving this total with no breakdown.")
    return None


def zero_without_printed_zero(value: Optional[float], lines: Sequence[Line]) -> Optional[str]:
    """4. A zero that no printed amount backs (agents only).

    A zero is accepted when its printed lines carry amounts; rule 5 then
    checks that they add up to zero."""
    if value is not None and abs(value) < CENT and not any(line.amount is not None for line in lines):
        return ("Give the printed amount of the line that shows this zero, such as 0 or a dash, "
                "because a zero needs a printed source like any other figure.")
    return None


def forced_balance(value: Optional[float], lines: Sequence[Line]) -> Optional[str]:
    """5. A value that is not the sum of its printed lines, such as a residual (agents only)."""
    if value is None or not lines:
        return None
    if any(line.amount is None for line in lines):
        return ("Give the printed amount of each line given for this figure, so the value can be "
                "checked against them.")
    added = sum(line.coefficient * line.amount for line in lines)
    if abs(added - value) > CENT:
        return (f"The printed lines given add up to {fmt_amount(added)} but the value given is "
                f"{fmt_amount(value)}, so check the sign of each line and whether a line is missing, "
                "because a value must be the sum of its printed lines and not a number found by subtraction.")
    return None


LABEL_LIMIT = 300


def label_too_long(lines: Sequence[Line]) -> Optional[str]:
    """Not a filing rule: a printed label is one line of the report, not a passage."""
    if any(len(line.printed_label.strip()) > LABEL_LIMIT for line in lines):
        return f"Keep each printed label to {LABEL_LIMIT} characters or fewer, as the line is printed."
    return None


def not_a_number(value: Optional[float], lines: Sequence[Line]) -> Optional[str]:
    """Not a filing rule: infinity or NaN is not an amount at all, and cannot be shown."""
    if value is not None and not math.isfinite(value):
        return "The value must be an ordinary number."
    if any(line.amount is not None and not math.isfinite(line.amount) for line in lines):
        return "The amount of each printed line must be an ordinary number."
    return None


def no_source(value: Optional[float], lines: Sequence[Line]) -> Optional[str]:
    """6. A figure with no source page or printed line."""
    if value is None:
        return None
    if not lines or any(int(line.page or 0) < 1 or not line.printed_label.strip() for line in lines):
        return ("Give the page and the line as printed for this figure, because every figure "
                "needs its source.")
    return None


def prior_year(period: str, first_statements: bool, locked: bool) -> Optional[str]:
    """7. A prior-year write on first financial statements, or over an imported figure."""
    if period == "PY" and first_statements:
        return "These are the company's first financial statements, so there is no prior year to save."
    if locked:
        return ("This prior-year figure is kept as filed in last year's workbook, so leave a "
                "comment if the report shows a different amount.")
    return None


def sign_question(open_question: bool, actor_kind: str) -> Optional[str]:
    """8. Only a person settles a sign-only difference with last year's workbook."""
    if open_question and actor_kind != "person":
        return ("Only a person can settle a sign-only difference with last year's workbook, "
                "so leave a comment for the reviewer.")
    return None


def typed_in_workbook(origin: Optional[str], actor_kind: str, from_workbook: bool = False) -> Optional[str]:
    """9. A figure a person typed into the workbook is kept fixed; only a person changes it. `from_workbook`:
    a this-year figure imported from the starting workbook, which stays fixed against agents after a person
    edits it too (its origin is then `person`), so the app and the filed workbook never disagree."""
    if (origin == "typed_in_workbook" or from_workbook) and actor_kind not in ("person", "import"):
        return ("A person typed this figure into the workbook, so leave a comment for the reviewer "
                "rather than changing it.")
    return None

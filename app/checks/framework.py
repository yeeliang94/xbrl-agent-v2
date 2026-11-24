"""Check results and the period-by-period comparison they share.

Copied from v1 `cross_checks/framework.py` (`Comparand`, `CrossCheckResult`),
`cross_checks/periods.py` and `cross_checks/_format.py`.

Statuses: `passed`, `failed`, `warning` (advisory), `not_applicable` (this
run's layout has nothing to check) and `not_assessed` (the check could not
be judged). v1's `pending` and `blocked` both become `not_assessed`, which
is never shown as a pass.

v2 checks Group filings twice: each check runs once for the Group columns
and once for the Company columns. So a check sees one entity at a time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.figures.sums import fmt_amount

DEFAULT_TOLERANCE = 1.0   # RM 1, as v1

_PERIOD_WORDS = {"CY": "this year", "PY": "last year"}


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def when(entity_scope: str, period: str) -> str:
    """"the Company, this year"."""
    return f"the {entity_scope}, {_PERIOD_WORDS.get(period, period)}"


def blank_sentence(names: list[str], entity_scope: str, period: str) -> str:
    """"Total assets is blank for the Company, this year." """
    return f"{_names(names)} {'is' if len(names) == 1 else 'are'} blank for {when(entity_scope, period)}."


def comparison_sentence(left_name: str, left: float, right_name: str, right: float, entity_scope: str,
                        period: str) -> str:
    """Two amounts that should agree, with the difference when they do not."""
    where = when(entity_scope, period)
    if abs(left - right) < 0.005:
        return f"For {where}, {left_name} and {right_name} agree at {fmt_amount(left)}."
    return (f"For {where}, {left_name} is {fmt_amount(left)} and {right_name} is {fmt_amount(right)}, "
            f"a difference of {fmt_amount(round(abs(left - right), 2))}.")


@dataclass
class Comparand:
    """One value a check looked at, and where it came from."""
    label: str
    sheet: str
    value: Optional[float] = None
    role: str = "leaf"          # lhs | rhs | leaf
    statement: str = ""
    row: Optional[int] = None
    period: str = "CY"
    tolerance: Optional[float] = None


@dataclass
class CheckResult:
    name: str
    status: str
    expected: Optional[float] = None
    actual: Optional[float] = None
    diff: Optional[float] = None
    tolerance: Optional[float] = None
    message: str = ""
    target_sheet: Optional[str] = None
    target_row: Optional[int] = None
    period: Optional[str] = None
    comparands: list[Comparand] = field(default_factory=list)


@dataclass(frozen=True)
class PeriodScope:
    entity_scope: str
    period: str

    @property
    def label(self) -> str:
        return f"{self.entity_scope} {self.period}"


def period_scopes(ctx) -> list[PeriodScope]:
    """The periods this check pass judges, for the one entity it is checking."""
    return [PeriodScope(ctx.entity_scope, period) for period in ctx.periods]


def company_suffix(ctx, scope: PeriodScope) -> str:
    return " [company]" if ctx.filing_level == "group" and scope.entity_scope == "Company" else ""


@dataclass
class PeriodEvaluation:
    spec: PeriodScope
    lhs: Optional[float]
    rhs: Optional[float]
    message: str
    comparands: list[Comparand]
    target_sheet: Optional[str] = None
    target_row: Optional[int] = None
    optional_when_both_missing: bool = True   # a prior year both sides omit is skipped

    def verdict(self, tolerance: float) -> str:
        if self.lhs is None and self.rhs is None and (
                self.spec.period == "PY" and self.optional_when_both_missing):
            return "skipped"
        if self.lhs is None or self.rhs is None:
            return "failed"
        return "passed" if abs(self.lhs - self.rhs) <= tolerance else "failed"

    @property
    def diff(self) -> Optional[float]:
        if self.lhs is None or self.rhs is None:
            return None
        return abs(self.lhs - self.rhs)


def combine_period_evaluations(name: str, evaluations: list[PeriodEvaluation],
                               tolerance: float) -> CheckResult:
    """One result for the periods. The first failing period carries the numbers."""
    verdicts = [e.verdict(tolerance) for e in evaluations]
    anchor = next((e for e in evaluations if e.verdict(tolerance) == "failed"), None) or next(
        (e for e in evaluations if e.verdict(tolerance) == "passed"), None)
    result = CheckResult(
        name=name, status="failed" if "failed" in verdicts else "passed", tolerance=tolerance,
        message=" ".join(e.message for e in evaluations),
        comparands=[c for e in sorted(evaluations, key=lambda e: e.spec.period == "CY")
                    if e.verdict(tolerance) != "skipped" for c in e.comparands],
    )
    if anchor is not None:
        result.expected, result.actual, result.diff = anchor.lhs, anchor.rhs, anchor.diff
        result.target_sheet, result.target_row = anchor.target_sheet, anchor.target_row
        result.period = anchor.spec.period
    return result

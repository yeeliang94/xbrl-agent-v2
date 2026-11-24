"""Checks inside one statement whose two sides come from different lines.

Copied from the `run_facts` halves of v1 `cross_checks/socf_articulation.py`
(opening cash + net change = closing cash) and
`cross_checks/attribution_footing.py` (profit, and comprehensive income,
agree with their split between owners and non-controlling interests).
v1 ran Group and Company inside one pass; v2 runs one entity per pass.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from app.catalog.statements import StatementType as S
from app.checks.figures_view import (
    CheckContext, LabelledValue, read_labelled_value, read_labelled_value_last, read_socf_net_change,
)
from app.checks.framework import (
    CheckResult, Comparand, blank_sentence, company_suffix, comparison_sentence, fmt_amount, period_scopes, when,
)


def _effective_tolerance(tolerance: float, *magnitudes: Optional[float]) -> float:
    """The RM 1 floor, growing with size so a large company's rounding is absorbed."""
    return max(tolerance, 1e-6 * max((abs(m) for m in magnitudes if m is not None), default=0.0))


class SOCFArticulationCheck:
    name = "socf_articulation"
    title = "Net change in cash agrees to cash balances"
    required_statements = {S.SOCF}

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def _period(self, ctx: CheckContext, tolerance: float, period: str) -> CheckResult:
        scope = ctx.entity_scope
        b = read_labelled_value(ctx, S.SOCF, "cash and cash equivalents at beginning of period", period, scope)
        e = read_labelled_value(ctx, S.SOCF, "cash and cash equivalents at end of period", period, scope)
        n = read_socf_net_change(ctx, period, scope)
        sheet = n.sheet or e.sheet or b.sheet or "SOCF"
        if b.value is None or n.value is None or e.value is None:
            passed = False
            message = blank_sentence([name for name, lv in (
                ("Cash at beginning of period", b), ("Net change in cash", n), ("Cash at end of period", e))
                if lv.value is None], scope, period)
        else:
            expected = b.value + n.value
            diff = abs(e.value - expected)
            passed = diff <= _effective_tolerance(tolerance, b.value, n.value, e.value)
            message = (f"For {when(scope, period)}, cash at beginning of period {fmt_amount(b.value)} plus "
                       f"the net change {fmt_amount(n.value)} is {fmt_amount(expected)}, and cash at end of "
                       f"period is {fmt_amount(e.value)}"
                       + ("." if diff < 0.005 else f", a difference of {fmt_amount(round(diff, 2))}."))
        suffix = " [company]" if ctx.filing_level == "group" and scope == "Company" else ""
        socf = S.SOCF.value
        complete = None not in (b.value, n.value, e.value)
        return CheckResult(
            name=self.name, status="passed" if passed else "failed",
            expected=(b.value + n.value) if b.value is not None and n.value is not None else None,
            actual=e.value, diff=abs(e.value - (b.value + n.value)) if complete else None,
            tolerance=tolerance, message=message, target_sheet=sheet, target_row=n.row, period=period,
            comparands=[
                Comparand(f"Cash and cash equivalents at end of period{suffix}", sheet, e.value, "lhs",
                          socf, e.row, period),
                Comparand(f"Cash and cash equivalents at beginning of period{suffix}", sheet, b.value,
                          "leaf", socf, b.row, period),
                Comparand(f"Net increase (decrease) in cash and cash equivalents{suffix}", sheet, n.value,
                          "leaf", socf, n.row, period),
            ])

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        current = self._period(ctx, tolerance, "CY")
        if "PY" not in ctx.periods:
            return current
        previous = self._period(ctx, tolerance, "PY")
        # A comparative counts only when its cash lines, or a non-zero movement, were presented.
        presented = any(c.value is not None and ("Net increase" not in c.label or c.value != 0)
                        for c in previous.comparands)
        if not presented:
            return current
        selected = current if current.status != "passed" else previous
        return replace(selected, message=f"{current.message} {previous.message}",
                       comparands=current.comparands + previous.comparands)


class _AttributionFooting:
    name = ""
    title = ""
    required_statements: set = set()
    _stmt = S.SOPL
    _income_label = ""
    _attribution_label = ""
    _noun = ""
    _income_name = ""
    _split_name = ""
    _owners_name = ""
    _owner_labels: tuple[str, ...] = ()

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def _attribution(self, ctx: CheckContext, period: str, scope: str) -> LabelledValue:
        raise NotImplementedError

    def _evaluate(self, ctx, spec, income: LabelledValue, attribution: LabelledValue, tolerance,
                  require: bool) -> dict:
        suffix = company_suffix(ctx, spec)
        sheet = attribution.sheet or income.sheet or self._stmt.value
        if income.value is not None and attribution.value is None and require:
            return {"verdict": "failed",
                    "msg": blank_sentence([self._owners_name], spec.entity_scope, spec.period),
                    "comparands": [Comparand(self._income_label, sheet, income.value, "lhs", self._stmt.value,
                                             income.row, spec.period)],
                    "expected": income.value, "actual": None, "diff": None, "row": attribution.row,
                    "sheet": sheet, "period": spec.period}
        if income.value is None or attribution.value is None:
            return {"verdict": "not_applicable", "comparands": [],
                    "msg": (f"For {when(spec.entity_scope, spec.period)}, {self._income_name} is blank, so its "
                            "attribution is not checked." if income.value is None else
                            f"For {when(spec.entity_scope, spec.period)}, the split of {self._noun} between "
                            "owners and non-controlling interests is not saved, so it is not checked.")}
        diff = abs(income.value - attribution.value)
        tol = _effective_tolerance(tolerance, income.value, attribution.value)
        passed = diff <= tol
        return {
            "verdict": "passed" if passed else "failed",
            "msg": comparison_sentence(self._income_name, income.value, self._split_name, attribution.value,
                                       spec.entity_scope, spec.period),
            "comparands": [
                Comparand(self._income_label + suffix, sheet, income.value, "lhs", self._stmt.value,
                          income.row, spec.period, tol),
                Comparand(self._attribution_label + suffix, sheet, attribution.value, "rhs",
                          self._stmt.value, attribution.row, spec.period, tol)],
            "expected": income.value, "actual": attribution.value, "diff": diff,
            "sheet": sheet, "row": attribution.row, "period": spec.period}

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        company_filing = ctx.filing_level == "company"
        evals = []
        for spec in period_scopes(ctx):
            # A rolled-forward prior year is read-only, so its owners line is not required.
            require = company_filing and not (spec.period == "PY" and ctx.prior_year_imported)
            income = read_labelled_value(ctx, self._stmt, self._income_label, spec.period, spec.entity_scope)
            attribution = self._attribution(ctx, spec.period, spec.entity_scope)
            if require and not any(read_labelled_value_last(ctx, self._stmt, owner, spec.period,
                                                            spec.entity_scope).value is not None
                                   for owner in self._owner_labels):
                attribution = LabelledValue(None, attribution.sheet, attribution.row)
            evals.append(self._evaluate(ctx, spec, income, attribution, tolerance, require))
        verdicts = [e["verdict"] for e in evals]
        status = "failed" if "failed" in verdicts else "passed" if "passed" in verdicts else "not_applicable"
        anchor = next((e for e in evals if e["verdict"] == "failed"), None) or next(
            (e for e in evals if e["verdict"] == "passed"), None)
        result = CheckResult(name=self.name, status=status, tolerance=tolerance,
                             message=" ".join(e["msg"] for e in evals),
                             comparands=[c for e in evals for c in e["comparands"]])
        if anchor:
            result.expected, result.actual, result.diff = anchor["expected"], anchor["actual"], anchor["diff"]
            result.target_sheet, result.target_row, result.period = anchor["sheet"], anchor["row"], anchor["period"]
        return result


class SOPLAttributionFootingCheck(_AttributionFooting):
    name = "sopl_attribution_footing"
    title = "Profit agrees to its attribution to owners"
    required_statements = {S.SOPL}
    _stmt = S.SOPL
    _income_label = "profit (loss)"
    _attribution_label = "total profit (loss)"
    _noun = "profit"
    _income_name = "Profit (loss)"
    _split_name = "the total of its attribution to owners and non-controlling interests"
    _owners_name = "Profit (loss), attributable to owners of parent"
    _owner_labels = ("profit (loss), attributable to owners of parent",)

    def _attribution(self, ctx, period, scope):
        # Exact-label reads only: "total profit (loss)" partly matches the income line.
        attr = read_labelled_value_last(ctx, self._stmt, self._attribution_label, period, scope)
        if attr.row is not None:
            return attr
        attr = read_labelled_value_last(ctx, self._stmt, self._income_label, period, scope)
        income = read_labelled_value(ctx, self._stmt, self._income_label, period, scope)
        if attr.row is not None and attr.row == income.row:
            return LabelledValue(None, attr.sheet, attr.row)
        return attr


class SOCIAttributionFootingCheck(_AttributionFooting):
    name = "soci_attribution_footing"
    title = "Comprehensive income agrees to its attribution to owners"
    required_statements = {S.SOCI}
    _stmt = S.SOCI
    _income_label = "total comprehensive income"
    _attribution_label = "total comprehensive income"
    _noun = "total comprehensive income"
    _income_name = "Total comprehensive income"
    _split_name = "the total of its attribution to owners and non-controlling interests"
    _owners_name = "Total comprehensive income, attributable to owners of parent"
    _owner_labels = ("total comprehensive income, attributable to owners of parent",
                     "comprehensive income, attributable to owners of parent")

    def _attribution(self, ctx, period, scope):
        # SOCI repeats the label: the first is the income side, the last the split.
        attr = read_labelled_value_last(ctx, self._stmt, self._attribution_label, period, scope)
        income = read_labelled_value(ctx, self._stmt, self._income_label, period, scope)
        if attr.row is not None and income.row is not None and attr.row == income.row:
            return LabelledValue(None, attr.sheet, attr.row)
        return attr

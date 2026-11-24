"""Checks that compare totals across statements.

Copied from the `run_facts` halves of v1 `cross_checks/sofp_balance.py`,
`sopl_to_socie_profit.py`, `soci_to_socie_tci.py`, `socie_to_sofp_equity.py`,
`socf_to_sofp_cash.py` and `sore_to_sofp_retained_earnings.py`. The workbook
halves (`run`) are not copied: v2 has no filled workbook.
"""
from __future__ import annotations

from app.catalog.statements import StatementType as S
from app.checks.figures_view import (
    CheckContext, LabelledValue, is_sore_run, read_labelled_value, read_labelled_value_last, read_matrix_row_sum,
    read_matrix_value, socie_component_cols, socie_has_nci, socie_retained_col, socie_total_col,
)
from app.checks.framework import (
    CheckResult, Comparand, PeriodEvaluation, blank_sentence, combine_period_evaluations, company_suffix,
    comparison_sentence, period_scopes, when,
)


def _compare_message(spec, left_name, left, right_name, right):
    if left is None and right is None and spec.period == "PY":
        return (f"For {when(spec.entity_scope, spec.period)}, {left_name} and {right_name} are both "
                "blank, so this period is not checked.")
    if left is None or right is None:
        blank = [name for name, value in ((left_name, left), (right_name, right)) if value is None]
        return blank_sentence(blank, spec.entity_scope, spec.period)
    return comparison_sentence(left_name, left, right_name, right, spec.entity_scope, spec.period)


def _pair(ctx, spec, left: LabelledValue, right: LabelledValue, *, labels, statements, names,
          message=None, target_right=False) -> PeriodEvaluation:
    suffix = company_suffix(ctx, spec)
    sheets = (left.sheet or statements[0].value, right.sheet or statements[1].value)
    return PeriodEvaluation(
        spec=spec, lhs=left.value, rhs=right.value,
        message=message or _compare_message(spec, names[0], left.value, names[1], right.value),
        target_sheet=sheets[1] if target_right else None,
        target_row=right.row if target_right else None,
        comparands=[
            Comparand(f"{labels[0]}{suffix}", sheets[0], left.value, "lhs", statements[0].value,
                      left.row, spec.period),
            Comparand(f"{labels[1]}{suffix}", sheets[1], right.value, "rhs", statements[1].value,
                      right.row, spec.period),
        ],
    )


class SOFPBalanceCheck:
    name = "sofp_balance"
    title = "Total assets equal total equity and liabilities"
    required_statements = {S.SOFP}

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            assets = read_labelled_value(ctx, S.SOFP, "total assets", spec.period, spec.entity_scope)
            eq_li = read_labelled_value(ctx, S.SOFP, "total equity and liabilities", spec.period,
                                        spec.entity_scope)
            evaluations.append(_pair(
                ctx, spec, assets, eq_li, labels=("Total assets", "Total equity and liabilities"),
                statements=(S.SOFP, S.SOFP), names=("Total assets", "Total equity and liabilities"),
                target_right=True))
        return combine_period_evaluations(self.name, evaluations, tolerance)


class SOPLToSOCIEProfitCheck:
    name = "sopl_to_socie_profit"
    title = "Profit for the year agrees to changes in equity"
    required_statements = {S.SOPL, S.SOCIE}

    def applies_to(self, ctx: CheckContext) -> bool:
        return not is_sore_run(ctx)

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            sopl = read_labelled_value(ctx, S.SOPL, "profit (loss)", spec.period, spec.entity_scope)
            col = (socie_total_col(ctx.filing_standard)
                   if socie_has_nci(ctx, spec.period, spec.entity_scope)
                   else socie_retained_col(ctx.filing_standard))
            socie = read_matrix_value(ctx, S.SOCIE, "profit (loss)", col, spec.period, spec.entity_scope)
            evaluations.append(_pair(ctx, spec, sopl, socie, labels=("Profit (loss)", "Profit (loss)"),
                                     statements=(S.SOPL, S.SOCIE),
                                     names=("Profit (loss) in SOPL", "Profit (loss) in SOCIE")))
        return combine_period_evaluations(self.name, evaluations, tolerance)


class SOCIToSOCIETCICheck:
    name = "soci_to_socie_tci"
    title = "Total comprehensive income agrees to changes in equity"
    required_statements = {S.SOCI, S.SOCIE}

    def applies_to(self, ctx: CheckContext) -> bool:
        return not is_sore_run(ctx)

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            soci = read_labelled_value(ctx, S.SOCI, "total comprehensive income", spec.period,
                                       spec.entity_scope)
            socie = read_matrix_value(ctx, S.SOCIE, "total comprehensive income",
                                      socie_total_col(ctx.filing_standard), spec.period, spec.entity_scope)
            evaluations.append(_pair(
                ctx, spec, soci, socie,
                labels=("Total comprehensive income", "Total comprehensive income"),
                statements=(S.SOCI, S.SOCIE), names=("Total comprehensive income in SOCI",
                                                     "Total comprehensive income in SOCIE")))
        return combine_period_evaluations(self.name, evaluations, tolerance)


class SOCIEToSOFPEquityCheck:
    name = "socie_to_sofp_equity"
    title = "Closing equity agrees to financial position"
    required_statements = {S.SOCIE, S.SOFP}

    def applies_to(self, ctx: CheckContext) -> bool:
        return not is_sore_run(ctx)

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            col = socie_total_col(ctx.filing_standard)
            socie = read_matrix_value(ctx, S.SOCIE, "equity at end of period", col, spec.period,
                                      spec.entity_scope)
            if socie.value is None:
                cols = [col] if ctx.filing_standard == "mpers" else socie_component_cols(ctx.filing_standard)
                socie = read_matrix_row_sum(ctx, S.SOCIE, "equity at end of period", cols, spec.period,
                                            spec.entity_scope)
            sofp = read_labelled_value(ctx, S.SOFP, "total equity", spec.period, spec.entity_scope)
            evaluations.append(_pair(ctx, spec, socie, sofp,
                                     labels=("Equity at end of period", "Total equity"),
                                     statements=(S.SOCIE, S.SOFP),
                                     names=("Equity at end of period in SOCIE", "Total equity in SOFP")))
        return combine_period_evaluations(self.name, evaluations, tolerance)


class SOCFToSOFPCashCheck:
    name = "socf_to_sofp_cash"
    title = "Cash at end of year agrees to financial position"
    required_statements = {S.SOCF, S.SOFP}

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            socf = read_labelled_value(ctx, S.SOCF, "cash and cash equivalents at end of period",
                                       spec.period, spec.entity_scope)
            sofp = read_labelled_value(ctx, S.SOFP, ["total cash and cash equivalents",
                                                     "total cash and bank balances",
                                                     "cash and cash equivalents"],
                                       spec.period, spec.entity_scope)
            message = None
            names = ("Cash at end of period in SOCF", "Cash and cash equivalents in SOFP")
            if socf.value is not None and sofp.value is not None and sofp.value == 0 and socf.value != 0 \
                    and abs(socf.value - sofp.value) > tolerance:
                message = (_compare_message(spec, names[0], socf.value, names[1], sofp.value)
                           + " Cash in SOFP is 0, so the balance sheet probably shows a cash line that "
                           "was not saved.")
            evaluations.append(_pair(
                ctx, spec, socf, sofp,
                labels=("Cash and cash equivalents at end of period", "Cash and cash equivalents"),
                statements=(S.SOCF, S.SOFP), names=names, message=message))
        return combine_period_evaluations(self.name, evaluations, tolerance)


class SOPLToSoREProfitCheck:
    """Added in step 9 (v1 had no SoRE profit check): profit in the retained earnings statement is an
    input in mTool, so it is compared with profit or loss as the equity grid's profit is."""
    name = "sopl_to_sore_profit"
    title = "Profit for the year agrees to retained earnings"
    required_statements = {S.SOPL, S.SOCIE}
    applies_to_standard = frozenset({"mpers"})

    def applies_to(self, ctx: CheckContext) -> bool:
        return is_sore_run(ctx)

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            sopl = read_labelled_value(ctx, S.SOPL, "profit (loss)", spec.period, spec.entity_scope)
            # The exact line: "Total Profit (loss)" works it out and the heading of the same name holds nothing.
            sore = read_labelled_value_last(ctx, S.SOCIE, "Profit (loss)", spec.period, spec.entity_scope)
            evaluations.append(_pair(ctx, spec, sopl, sore, labels=("Profit (loss)", "Profit (loss)"),
                                     statements=(S.SOPL, S.SOCIE),
                                     names=("Profit (loss) in SOPL", "Profit (loss) in SoRE"), target_right=True))
        return combine_period_evaluations(self.name, evaluations, tolerance)


class SoREToSOFPRetainedEarningsCheck:
    name = "sore_to_sofp_retained_earnings"
    title = "Retained earnings agree to financial position"
    required_statements = {S.SOCIE, S.SOFP}
    applies_to_standard = frozenset({"mpers"})

    def applies_to(self, ctx: CheckContext) -> bool:
        return is_sore_run(ctx)

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        evaluations = []
        for spec in period_scopes(ctx):
            sore = read_labelled_value(ctx, S.SOCIE, "retained earnings at end of period", spec.period,
                                       spec.entity_scope)
            sofp = read_labelled_value(ctx, S.SOFP, ["Retained earnings"], spec.period, spec.entity_scope)
            evaluations.append(_pair(ctx, spec, sore, sofp,
                                     labels=("Retained earnings at end of period", "Retained earnings"),
                                     statements=(S.SOCIE, S.SOFP),
                                     names=("Retained earnings at end of period in SoRE",
                                            "Retained earnings in SOFP")))
        return combine_period_evaluations(self.name, evaluations, tolerance)

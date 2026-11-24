"""Totals as the report gives them agree with the lines saved under them.

New in v2. v1 raised a conflict when a total typed by an agent differed from
its parts. v2 never stores a typed value on an ordinary total: it keeps the
amount the report prints beside the sum of the saved lines. A total the
report gives with no breakdown keeps its typed value, and lines saved under
it later may add up to something else. This check lists both kinds of
difference. It warns rather than fails, and never decides which side is
right: either the total or a line may be the misreading.
"""
from __future__ import annotations

from app.checks.figures_view import CheckContext
from app.checks.framework import CheckResult, fmt_amount, when
from app.figures.sums import add_up


def _difference(left: float, right: float) -> str:
    return f", a difference of {fmt_amount(round(abs(left - right), 2))}."


class PrintedTotalsCheck:
    name = "printed_totals"
    title = "Printed totals agree with their lines"
    required_statements: set = set()

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        scope = ctx.entity_scope
        label_of = {line.concept_uuid: line.label.lstrip("*").strip()
                    for lines in ctx.lines.values() for line in lines}
        stated = {(uuid, period): value for (uuid, period, entity), value in ctx.stated.items()
                  if entity == scope and uuid in label_of}
        typed = {(uuid, period) for (uuid, period, entity) in ctx.no_breakdown
                 if entity == scope and uuid in label_of}
        if not stated and not typed:
            return CheckResult(self.name, "not_assessed", message="No printed totals are saved.")
        differences = []
        for uuid, period in sorted(stated.keys() | typed, key=lambda key: (key[1], label_of[key[0]])):
            label, where = label_of[uuid], when(scope, period)
            saved = ctx.values.get((uuid, period, scope, ""))
            if (uuid, period) in stated:
                printed = stated[(uuid, period)]
                if saved is None:
                    differences.append(f"For {where}, the report prints {label} as {fmt_amount(printed)}, "
                                       "but no line under it is saved.")
                elif abs(saved - printed) > tolerance:
                    differences.append(f"For {where}, the report prints {label} as {fmt_amount(printed)}, "
                                       f"but the saved lines add up to {fmt_amount(saved)}"
                                       + _difference(printed, saved))
            if (uuid, period) in typed and saved is not None:
                added = add_up(ctx.edges.get(uuid, []),
                               lambda child: ctx.values.get((child, period, scope, "")))
                if added is not None and abs(added - saved) > tolerance:
                    differences.append(f"For {where}, {label} is saved as {fmt_amount(saved)} with no "
                                       f"breakdown, but the lines saved under it add up to {fmt_amount(added)}"
                                       + _difference(saved, added))
        if differences:
            return CheckResult(self.name, "warning", message=" ".join(differences))
        return CheckResult(self.name, "passed", message="Every printed total agrees with its lines.")

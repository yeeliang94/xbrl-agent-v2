"""Checks on the numeric notes (issued capital, related parties).

- `NotesNumericFootingCheck`: copied from v1 `cross_checks/notes_numeric_footing.py`
  (category totals, share roll-forwards, opening equals last year's closing),
  reading the in-memory figures instead of SQL.
- `NotesFaceTieoutCheck`: rebuilt from v1 `cross_checks/notes_face_tieouts.py`,
  which read a filled workbook. Same one curated pair: share capital on the
  balance sheet equals the issued-capital note's closing amount.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.catalog.dimensions import numeric_category_catalog
from app.catalog.statements import StatementType as S
from app.checks.figures_view import CheckContext, label_candidates, read_labelled_value
from app.checks.framework import CheckResult, Comparand, fmt_amount

_TOLERANCE = 1.0


@dataclass(frozen=True)
class _Block:
    title: str
    balance: str
    issued: tuple[str, ...]
    components: tuple[str, ...] = ()
    other: str = ""


_BLOCKS = (
    _Block("Amount of shares issued and fully paid",
           balance="AmountOfSharesIssuedAndFullyPaidOutstanding",
           issued=("AmountOfSharesIssuedAndFullyPaidDuringPeriod",),
           components=("AmountOfSharesIssuedForCashUnderESOS",
                       "AmountOfSharesIssuedForCashUnderPrivatePlacement",
                       "AmountOfSharesArisingFromConversionOfICULSBySurrenderOption",
                       "AmountOfSharesArisingFromConversionOfICULSByMandatoryConversion"),
           other="AmountOfOtherChangesInSharesIssuedAndFullyPaid"),
    _Block("Number of shares outstanding", balance="NumberOfSharesOutstanding",
           issued=("NumberOfOutstandingSharesIssuedDuringPeriod", "NumberOfSharesIssued"),
           other="OtherChangesInNumberOfSharesOutstandingDuringPeriod"),
    _Block("Amount of shares outstanding", balance="AmountOfSharesOutstanding",
           issued=("AmountOfOutstandingSharesIssuedDuringPeriod",),
           other="OtherChangesInAmountOfSharesOutstanding"),
)
_TOPICS = {"ISSUED_CAPITAL": ("Issued capital", "ClassesOfShareCapitalAxis"),
           "RELATED_PARTY": ("Related parties", "CategoriesOfRelatedPartiesAxis")}


def _local(name: str | None) -> str:
    return (name or "").split("_", 1)[-1]


def _member_label(member: str) -> str:
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", _local(member).removesuffix("Member"))
    return words[:1].upper() + words[1:].lower()


class NotesNumericFootingCheck:
    name = "notes_numeric_footing"
    title = "Share capital and related-party notes add up"
    required_statements: set = set()

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        catalog = numeric_category_catalog(ctx.filing_standard)
        roots = numeric_category_catalog(ctx.filing_standard, roots_only=True)
        findings: list[str] = []
        assessed = False
        for note, (topic, axis_suffix) in _TOPICS.items():
            lines = {line.concept_uuid: line for line in ctx.lines.get(ctx.note_template_ids.get(note, ""), [])}
            values: dict[tuple[str, str, str], float] = {}
            for (uuid, period, scope, dims), value in ctx.values.items():
                if uuid not in lines or scope != ctx.entity_scope:
                    continue
                dimensions = json.loads(dims or "{}")
                category = ""
                if dimensions:
                    axis, member = next(iter(dimensions.items()))
                    if len(dimensions) > 1 or not axis.endswith(axis_suffix) or member not in catalog.get(axis, []):
                        continue
                    category = "" if member in roots.get(axis, []) else member
                values[(uuid, period, category)] = value
            if not values:
                continue
            assessed = True
            names: dict[str, list[str]] = {}
            for uuid, line in sorted(lines.items(), key=lambda item: item[1].row):
                names.setdefault(_local(line.primary_concept), []).append(uuid)
            block_of = {uuid: b.title for b in _BLOCKS for uuid in names.get(b.balance, [])}

            def report(uuid, period, category, expected, actual, detail):
                if abs(expected - actual) <= _TOLERANCE:
                    return
                field = lines[uuid].label.lstrip("*").strip()
                if uuid in block_of and field.lower().startswith("balance"):
                    field = f"{block_of[uuid]}, {field[:1].lower()}{field[1:]}"
                where = ", ".join(filter(None, [_member_label(category) if category else "Total", period,
                                                ctx.entity_scope if ctx.filing_level == "group" else ""]))
                findings.append(f"{topic}, {field} ({where}): {detail}")

            groups: dict[tuple[str, str], dict[str, float]] = {}
            for (uuid, period, category), value in values.items():
                groups.setdefault((uuid, period), {})[category] = value
            for (uuid, period), by_category in sorted(groups.items()):
                parts = {c: v for c, v in by_category.items() if c}
                if "" in by_category and parts:
                    total = sum(parts.values())
                    report(uuid, period, "", total, by_category[""],
                           f"the categories add up to {fmt_amount(total)}, but the total is "
                           f"{fmt_amount(by_category[''])}.")
            if note != "ISSUED_CAPITAL":
                continue
            keys = {(p, c) for (_u, p, c) in values}
            for block in _BLOCKS:
                balances = names.get(block.balance, [])
                if len(balances) != 2:
                    continue
                opening, closing = balances
                for period, category in sorted(keys):
                    def get(uuid, p=period):
                        return values.get((uuid, p, category))
                    start, end = get(opening), get(closing)
                    if start is not None and end is not None:
                        issued = next((get(u) for name in block.issued for u in names.get(name, [])
                                       if get(u) is not None), None)
                        if issued is None:
                            issued = sum(get(u) or 0.0 for name in block.components for u in names.get(name, []))
                        other = sum(get(u) or 0.0 for u in names.get(block.other, []))
                        expected = start + issued + other
                        report(closing, period, category, expected, end,
                               f"opening {fmt_amount(start)} plus movements {fmt_amount(issued + other)} is "
                               f"{fmt_amount(expected)}, but the closing balance is {fmt_amount(end)}.")
                    prior_end = get(closing, "PY")
                    if period == "CY" and start is not None and prior_end is not None:
                        report(opening, period, category, prior_end, start,
                               f"the opening balance {fmt_amount(start)} differs from the prior year's "
                               f"closing balance {fmt_amount(prior_end)}.")
        if not assessed:
            return CheckResult(self.name, "not_assessed", message="No issued-capital or related-party figures are saved.")
        if findings:
            return CheckResult(self.name, "warning", message="; ".join(findings))
        return CheckResult(self.name, "passed", message="The note figures add up.")


class NotesFaceTieoutCheck:
    name = "notes_face_tieouts"
    title = "Share capital agrees to the issued-capital note"
    required_statements = {S.SOFP}

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        """Current year only, as v1. A gap of about 1,000 times is a unit mix-up."""
        face = read_labelled_value(ctx, S.SOFP, ["share capital", "issued capital"], "CY", ctx.entity_scope)
        note_lines = ctx.lines.get(ctx.note_template_ids.get("ISSUED_CAPITAL", ""), [])
        note = None
        for line in label_candidates(note_lines, "balance at the end of period"):
            # The issued-and-fully-paid block's closing balance, never "outstanding" (treasury shares).
            if _local(line.primary_concept) == "AmountOfSharesIssuedAndFullyPaidOutstanding":
                note = ctx.values.get((line.concept_uuid, "CY", ctx.entity_scope, ""))
                if note is not None:
                    break
        if face.value is None or note is None:
            return CheckResult(self.name, "not_assessed",
                               message="Share capital is not saved on both the balance sheet and the note.")
        scale = max(abs(face.value), abs(note))
        comparands = [Comparand("Share capital", face.sheet or "SOFP", face.value, "lhs", S.SOFP.value,
                                face.row, "CY"),
                      Comparand("Issued capital, balance at the end of period", "Notes-Issuedcapital", note,
                                "rhs", "", None, "CY")]
        if abs(face.value - note) > max(1.0, 5e-3 * scale):
            return CheckResult(
                self.name, "failed", expected=face.value, actual=note, diff=abs(face.value - note),
                period="CY", target_sheet=face.sheet, target_row=face.row, comparands=comparands,
                message=(f"{ctx.entity_scope} share capital: the balance sheet shows {fmt_amount(face.value)} "
                         f"but the note shows {fmt_amount(note)}; check the note for a wrong scale or a "
                         "transcription error."))
        return CheckResult(self.name, "passed", expected=face.value, actual=note, diff=abs(face.value - note),
                           period="CY", comparands=comparands,
                           message=f"{ctx.entity_scope} share capital agrees with the note.")

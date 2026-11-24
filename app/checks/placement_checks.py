"""Advisory checks rebuilt from v1 checks that read a filled workbook.

- `SOCFSectionPlacementCheck`, from v1 `cross_checks/socf_section_placement.py`:
  a cash-flow line saved under one activity (operating, investing, financing)
  that the report prints under another. Moving a line between sections does
  not change total cash, so no arithmetic check can see it. v1 compared the
  workbook with the scout's reading; v2 compares each figure's template
  section with the section its printed line was saved under. It warns, never
  fails, as in v1.
- `NotesCitationCheck`, from v1 `cross_checks/notes_consistency.py`: a policy
  note and its matching disclosure note cite pages with no overlap (one may
  cite the printed folio, not the PDF page). v1 placed the same policy text
  in both cells, so their citations had to agree. v2 places each note once
  (one note, one field), so a policy note and its disclosure note sit on
  their own pages and different pages are expected: comparing them would
  warn on nearly every run. Until there is a citation both share (a page
  reference printed in the text, say), it reports "not assessed" and says
  why. `citation_disagreements` is kept for that comparison.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from app.catalog.statements import StatementType as S
from app.checks.figures_view import CheckContext
from app.checks.framework import CheckResult

_SECTIONS = ("operating", "investing", "financing")


def classify_section(heading: Optional[str]) -> Optional[str]:
    """operating, investing or financing, or None when the heading names none or two."""
    if not heading:
        return None
    hits = [s for s in _SECTIONS if s in str(heading).lower()]
    return hits[0] if len(hits) == 1 else None


def _norm(label: str) -> str:
    text = re.sub(r"\s+", " ", str(label or "").strip().lstrip("*").strip())
    return text.rstrip(":.").strip().lower()


class SOCFSectionPlacementCheck:
    name = "socf_section_placement"
    title = "Cash flow lines sit in the section the report prints them in"
    required_statements = {S.SOCF}

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        template_id = ctx.template_ids.get(S.SOCF)
        lines = sorted(ctx.lines.get(template_id or "", []), key=lambda line: (line.sheet, line.row))
        section_of: dict[str, str] = {}
        current = None
        for line in lines:
            section = classify_section(line.label)
            if section is not None and line.kind == "ABSTRACT":
                current = section
                continue
            if current is not None and line.kind != "ABSTRACT":
                section_of.setdefault(line.concept_uuid, current)
        compared, warnings = 0, []
        for (uuid, period, scope), printed in sorted(ctx.printed.items()):
            if scope != ctx.entity_scope or uuid not in section_of:
                continue
            for label, printed_section in printed:
                source = classify_section(printed_section)
                if source is None:
                    continue
                compared += 1
                placed = section_of[uuid]
                if placed != source and label not in {w[0] for w in warnings}:
                    warnings.append((label, placed, source))
        if not compared:
            return CheckResult(self.name, "not_assessed",
                               message="No cash flow line was saved with the section it is printed under.")
        if warnings:
            return CheckResult(self.name, "warning", message="; ".join(
                f"'{label}' was saved under {placed} activities, but the report prints it under "
                f"{source} activities" for label, placed, source in warnings))
        return CheckResult(self.name, "passed", message="Each cash flow line sits in its printed section.")


# v1's curated pairs: a policy note and the disclosure note on the same topic.
TOPIC_PAIRS: tuple[tuple[str, str], ...] = (
    ("Description of accounting policy for cash and cash equivalents", "Disclosure of cash and cash equivalents"),
    ("Description of accounting policy for employee benefits", "Disclosure of employee benefits expense"),
    ("Description of accounting policy for deferred income tax", "Disclosure of deferred tax assets/(liabilities)"),
    ("Description of accounting policy for income tax", "Disclosure of income tax expense"),
    ("Description of accounting policy for leases", "Disclosure of leases"),
    ("Description of accounting policy for fair value measurement", "Disclosure of fair value measurement"),
    ("Description of accounting policy for financial instruments", "Disclosure of financial instruments"),
    ("Description of accounting policy for impairment of financial assets",
     "Disclosure of allowance for credit losses"),
    ("Description of accounting policy for recognition of revenue and other income",
     "Disclosure of revenue from contract customers"),
    ("Description of accounting policy for other provisions", "Disclosure of other provisions"),
    ("Description of accounting policy for property, plant and equipment",
     "Disclosure of property, plant and equipment"),
)


def citation_disagreements(policy_pages: dict[str, set[int]], note_pages: dict[str, set[int]],
                           pairs: Iterable[tuple[str, str]] = TOPIC_PAIRS) -> list[str]:
    """Paired notes whose cited pages do not overlap at all."""
    out = []
    for policy, disclosure in pairs:
        a, b = policy_pages.get(_norm(policy)), note_pages.get(_norm(disclosure))
        if a and b and a.isdisjoint(b):
            out.append(f"'{policy}' cites pages {sorted(a)} but '{disclosure}' cites pages {sorted(b)}; "
                       "one may cite the printed folio instead of the PDF page")
    return out


class NotesCitationCheck:
    name = "notes_citation_consistency"
    title = "Policy and disclosure notes cite the same pages"
    required_statements: set = set()

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        return CheckResult(self.name, "not_assessed", message="Each note is placed once, so a policy note and "
                           "its disclosure note have no shared citation to compare.")

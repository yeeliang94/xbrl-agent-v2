"""Last year's figures kept from the starting workbook agree with the report's comparatives.

Rebuilt from v1 `concept_model/prior_year.py` (`check_results`). The agent's
reading of each comparative is recorded by `app/starting/comparatives.py`;
this check lists every difference still open and how many kept figures were
compared at all. It warns and never decides: a difference may be a
restatement in the report or a slip in last year's filing, and the kept
figure never changes. A difference a person confirmed after the reading
counts as assessed. A sign-only difference stays open until a person
settles the figure's sign question.

Only face-statement figures with no category are counted: the figures
agent compares the face's comparatives, and a numeric note's figures (by
category) are never compared, so counting them would leave a warning nobody
can clear.
"""
from __future__ import annotations

import json
import sqlite3

from app.catalog.lookup import RunFamily
from app.checks.figures_view import CheckContext
from app.checks.framework import CheckResult, when
from app.figures.sums import CENT, fmt_amount


def comparisons(conn: sqlite3.Connection, family: RunFamily, entity_scope: str) -> list[dict]:
    """Each last-year face figure of one entity kept from the starting workbook, with its comparison if any."""
    faces = sorted(set(family.template_ids.values()))
    if not faces:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT f.id, f.concept_uuid, f.dimension_key, f.value, f.status, f.sign_question, c.report_value, "
        "c.disputed_value, c.page, c.reason, c.compared_at, "
        "EXISTS (SELECT 1 FROM figure_history h WHERE h.figure_id = f.id AND h.action = 'confirm' "
        "AND h.actor_kind = 'person' AND h.changed_at >= c.compared_at) AS accepted "
        "FROM figures f LEFT JOIN prior_year_comparisons c ON c.figure_id = f.id "
        "WHERE f.run_id = ? AND f.entity_scope = ? AND f.period = 'PY' AND f.origin = 'prior_workbook' "
        "AND f.locked = 1 AND f.status != 'not_disclosed' AND f.dimension_key = '' "
        "AND EXISTS (SELECT 1 FROM concept_nodes n WHERE n.concept_uuid = f.concept_uuid "
        f"AND n.template_id IN ({', '.join('?' * len(faces))})) ORDER BY f.id",
        (family.run_id, entity_scope, *faces))]


def open_differences(items: list[dict], tolerance: float) -> list[dict]:
    """The compared items whose difference is still open: not within tolerance, or a sign question, and not
    accepted by a person."""
    out = []
    for i in items:
        if i["report_value"] is None:
            continue
        sign_open = bool(i["sign_question"]) and i["disputed_value"] is not None
        if abs(float(i["report_value"]) - float(i["value"])) <= tolerance and not sign_open:
            continue
        if i["accepted"] and not sign_open:
            continue
        out.append({**i, "sign_open": sign_open})
    return out


def _category(dimension_key: str) -> str:
    if not dimension_key:
        return ""
    members = [m.split("_", 1)[-1].removesuffix("Member") for m in json.loads(dimension_key).values()]
    return " (" + ", ".join(members) + ")"


class PriorYearComparativesCheck:
    name = "prior_year_comparatives"
    title = "Last year's figures agree with the report"
    required_statements: set = set()

    def applies_to(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext, tolerance: float) -> CheckResult:
        items = ctx.comparisons
        if not items:
            return CheckResult(self.name, "not_applicable", message="No figures were kept from last year's workbook.")
        label_of = {line.concept_uuid: line.label.lstrip("*").strip()
                    for lines in ctx.lines.values() for line in lines}
        compared = [i for i in items if i["report_value"] is not None]
        if not compared:
            return CheckResult(self.name, "not_assessed", period="PY", message=(
                f"None of the {len(items)} figures kept from last year's workbook has been compared with the "
                "report yet."))
        where, problems, accepted = when(ctx.entity_scope, "PY"), [], 0
        for i in compared:
            kept, read = float(i["value"]), float(i["report_value"])
            sign_open = bool(i["sign_question"]) and i["disputed_value"] is not None
            if abs(read - kept) <= tolerance and not sign_open:
                continue
            if i["accepted"] and not sign_open:
                accepted += 1
                continue
            label = label_of.get(i["concept_uuid"], "A line") + _category(i["dimension_key"])
            if sign_open:
                text = (f"For {where}, {label} is {fmt_amount(kept)} in last year's workbook but the report shows "
                        f"{fmt_amount(float(i['disputed_value']))}: the same amount with the opposite sign, which "
                        "a person decides.")
                if i["reason"]:
                    text += f" The agent's reasoning: {i['reason'].rstrip('.')}."
            else:
                text = (f"For {where}, {label} is {fmt_amount(kept)} in last year's workbook but the report shows "
                        f"{fmt_amount(read)}, a difference of {fmt_amount(round(abs(read - kept), 2))}.")
            problems.append(text + (f" See page {i['page']}." if i["page"] else ""))
        coverage = (f"{len(compared)} of {len(items)} figures kept from last year's workbook were compared with "
                    "the report." + (f" {accepted} difference(s) were accepted by a person." if accepted else ""))
        status = "warning" if problems or len(compared) < len(items) else "passed"
        return CheckResult(self.name, status, period="PY", message=" ".join(problems + [coverage]))

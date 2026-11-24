"""Run every check on a run's saved figures and save the results.

Called by the figure store after every change, so `check_results` always
matches the figures. Gating follows v1 `cross_checks/framework.run_all_facts`:
a statement with no standalone page is not applicable; a statement missing
from the run, a statement with no figures yet, or a check that cannot run is
not assessed. Group filings get one result per check for the Group and one
for the Company.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from typing import Optional

from app.catalog.lookup import RunFamily, edges_for
from app.checks.comparatives_check import PriorYearComparativesCheck, comparisons
from app.checks.figures_view import CheckContext, Line
from app.checks.framework import DEFAULT_TOLERANCE, CheckResult
from app.checks.internal_checks import (
    SOCFArticulationCheck, SOCIAttributionFootingCheck, SOPLAttributionFootingCheck,
)
from app.checks.notes_checks import NotesFaceTieoutCheck, NotesNumericFootingCheck
from app.checks.placement_checks import NotesCitationCheck, SOCFSectionPlacementCheck
from app.checks.statement_checks import (
    SOCFToSOFPCashCheck, SOCIEToSOFPEquityCheck, SOCIToSOCIETCICheck, SOFPBalanceCheck,
    SoREToSOFPRetainedEarningsCheck, SOPLToSOCIEProfitCheck, SOPLToSoREProfitCheck,
)
from app.checks.totals_check import PrintedTotalsCheck
from app.db import now
from app.figures.sums import known_value

logger = logging.getLogger(__name__)


def all_checks() -> list:
    return [
        SOFPBalanceCheck(), SOPLToSOCIEProfitCheck(), SOCIToSOCIETCICheck(), SOCIEToSOFPEquityCheck(),
        SOCFToSOFPCashCheck(), SOCFArticulationCheck(), SOPLAttributionFootingCheck(),
        SOCIAttributionFootingCheck(), SoREToSOFPRetainedEarningsCheck(), SOPLToSoREProfitCheck(),
        NotesNumericFootingCheck(),
        NotesFaceTieoutCheck(), SOCFSectionPlacementCheck(), NotesCitationCheck(), PrintedTotalsCheck(),
        PriorYearComparativesCheck(),
    ]


def build_context(conn: sqlite3.Connection, family: RunFamily, entity_scope: str) -> CheckContext:
    lines: dict[str, list[Line]] = {}
    for template_id in family.all_template_ids():
        lines[template_id] = [Line(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in conn.execute(
            "SELECT n.concept_uuid, n.kind, n.canonical_label, n.render_sheet, n.render_row, n.matrix_col, "
            "a.primary_concept FROM concept_nodes n LEFT JOIN concept_semantic_addresses a "
            "ON a.concept_uuid = n.concept_uuid WHERE n.template_id = ? AND n.is_current = 1 "
            "ORDER BY n.render_row", (template_id,))]
    values: dict = {}
    printed: dict = {}
    no_breakdown: set = set()
    for r in conn.execute(
            "SELECT concept_uuid, period, entity_scope, dimension_key, value, status, children_status "
            "FROM figures WHERE run_id = ?", (family.run_id,)):
        value = known_value(r[4], r[5])
        if value is not None:
            values[(r[0], r[1], r[2], r[3])] = value
        if r[6] == "aggregate_only" and r[3] == "":
            no_breakdown.add((r[0], r[1], r[2]))
    for r in conn.execute(
            "SELECT f.concept_uuid, f.period, f.entity_scope, l.printed_label, l.section FROM figure_lines l "
            "JOIN figures f ON f.id = l.figure_id WHERE f.run_id = ? AND f.dimension_key = ''",
            (family.run_id,)):
        printed.setdefault((r[0], r[1], r[2]), []).append((r[3], r[4]))
    stated = {(r[0], r[1], r[2]): float(r[3]) for r in conn.execute(
        "SELECT concept_uuid, period, entity_scope, stated_value FROM figures WHERE run_id = ? "
        "AND dimension_key = '' AND stated_value IS NOT NULL", (family.run_id,))}
    imported = conn.execute("SELECT 1 FROM figures WHERE run_id = ? AND origin = 'prior_workbook' LIMIT 1",
                            (family.run_id,)).fetchone() is not None
    return CheckContext(
        run_id=family.run_id, filing_level=family.level, filing_standard=family.standard,
        entity_scope=entity_scope, periods=family.periods, template_ids=dict(family.template_ids),
        variants=dict(family.variants), note_template_ids=dict(family.note_template_ids),
        lines=lines, values=values, printed=printed, stated=stated, no_breakdown=no_breakdown,
        edges=edges_for(conn, family.all_template_ids()), prior_year_imported=imported,
        comparisons=comparisons(conn, family, entity_scope) if imported else [])


def _has_figures(ctx: CheckContext, template_id: str) -> bool:
    uuids = {line.concept_uuid for line in ctx.lines.get(template_id, [])}
    return any(key[0] in uuids and key[2] == ctx.entity_scope for key in ctx.values)


def _gate(check, ctx: CheckContext) -> Optional[CheckResult]:
    required = check.required_statements
    if ctx.filing_standard not in getattr(check, "applies_to_standard", {"mfrs", "mpers"}):
        return CheckResult(check.name, "not_applicable",
                           message=f"This check applies to {', '.join(sorted(check.applies_to_standard)).upper()} "
                                   "filings only.")
    skipped = sorted(s.value for s in required if ctx.variants.get(s) == "NotPrepared")
    if skipped:
        return CheckResult(check.name, "not_applicable",
                           message=f"{', '.join(skipped)} has no standalone statement in this report.")
    missing = sorted(s.value for s in required if s not in ctx.template_ids)
    if missing:
        return CheckResult(check.name, "not_assessed", message=(
            f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not part of this run."))
    if not check.applies_to(ctx):
        return CheckResult(check.name, "not_applicable", message="This check does not apply to this run's layouts.")
    empty = sorted(s.value for s in required if not _has_figures(ctx, ctx.template_ids[s]))
    if empty:
        return CheckResult(check.name, "not_assessed",
                           message=f"No {ctx.entity_scope} figures are saved for {', '.join(empty)} yet.")
    return None


def _target(ctx: CheckContext, result: CheckResult) -> Optional[str]:
    spots = [(result.target_sheet, result.target_row)] + [
        (c.sheet, c.row) for c in result.comparands if c.role in ("lhs", "rhs")]
    for sheet, row in spots:
        if row is None:
            continue
        for lines in ctx.lines.values():
            for line in lines:
                if line.sheet == sheet and line.row == row:
                    return line.concept_uuid
    return None


def run_checks(conn: sqlite3.Connection, family: RunFamily) -> list[dict]:
    """Recompute and save every check for the run. Returns the saved rows."""
    stamp = now()
    rows = []
    for entity_scope in family.entity_scopes:
        ctx = build_context(conn, family, entity_scope)
        for check in all_checks():
            result = _gate(check, ctx)
            if result is None:
                try:
                    result = check.run(ctx, DEFAULT_TOLERANCE)
                except Exception as exc:  # one broken check must not stop the others
                    logger.exception("Check %s failed to run", check.name)
                    result = CheckResult(check.name, "not_assessed", message=f"This check could not run: {exc}")
            rows.append((family.run_id, check.name, entity_scope, result.status, result.period,
                         result.expected, result.actual, result.diff, result.tolerance, result.message,
                         json.dumps([asdict(c) for c in result.comparands]) if result.comparands else None,
                         _target(ctx, result), stamp))
    conn.execute("DELETE FROM check_results WHERE run_id = ?", (family.run_id,))
    conn.executemany(
        "INSERT INTO check_results(run_id, check_name, entity_scope, status, period, expected, actual, diff, "
        "tolerance, message, comparands_json, target_concept_uuid, computed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return read_checks(conn, family.run_id)


TITLES = {check.name: check.title for check in all_checks()}


def read_checks(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    order = {check.name: i for i, check in enumerate(all_checks())}
    out = []
    for r in conn.execute("SELECT * FROM check_results WHERE run_id = ?", (run_id,)):
        out.append({
            "name": r["check_name"], "title": TITLES.get(r["check_name"], r["check_name"]),
            "entity_scope": r["entity_scope"], "status": r["status"], "period": r["period"],
            "expected": r["expected"], "actual": r["actual"], "diff": r["diff"], "tolerance": r["tolerance"],
            "message": r["message"],
            "comparands": json.loads(r["comparands_json"]) if r["comparands_json"] else [],
            "target_concept_uuid": r["target_concept_uuid"], "computed_at": r["computed_at"],
        })
    out.sort(key=lambda c: (c["entity_scope"] != "Group", order.get(c["name"], 99)))
    return out

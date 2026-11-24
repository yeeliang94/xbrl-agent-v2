"""The figures agent checks its own work: the checks, coverage, and the
finish.

The finish (v1 run 146 lost its whole run to a save gate that left an honest
agent no legal move): the agent is sent back, with every reason at once,
unless it saved figures, and after its last change ran the checks and
accounted for every printed line. After one refusal it may finish anyway by
listing each open point with its reason. Checks that still need action,
reported by run_checks, already count as that refusal (v1, owner's note
"trace_audit_183_185_fixes": it saves a turn). At the last step any finish
is taken, so the run keeps the agent's report.
"""
from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from app import db
from app.checks.comparatives_check import comparisons, open_differences
from app.checks.framework import DEFAULT_TOLERANCE
from app.checks.runner import all_checks, read_checks
from app.extraction import coverage
from app.extraction.coverage import CoverageLine
from app.extraction.outline import LINE
from app.extraction.state import FiguresDeps
from app.figures import store
from app.figures.sums import fmt_amount
from app.runs.events import figure_pages

ACTION = ("failed", "warning")
_REQUIRED = {c.name: {s.value for s in c.required_statements} for c in all_checks()}
COMPARATIVES = "prior_year_comparatives"
ALWAYS = {"printed_totals", COMPARATIVES}   # each covers every statement's own figures


def relevant_to(statements: str | Iterable[str], name: str, filled: Iterable[str] = ()) -> bool:
    """The checks on these statements' own figures, and the checks across statements that involve one of
    them when every other statement they need is already filled (`filled`): the equity statement's agent
    sees profit agree with profit or loss once that is filled. The notes checks wait for the notes agent."""
    own = {statements} if isinstance(statements, str) else set(statements)
    required = _REQUIRED.get(name, set())
    if name in ALWAYS:
        return True
    if not required or name.startswith("notes_"):
        return False
    return bool(required & own) and required <= own | set(filled)


def _relevant(deps: FiguresDeps, name: str) -> bool:
    return relevant_to(deps.statements, name, deps.filled)


def _current(deps: FiguresDeps) -> dict[tuple[str, str], dict]:
    with db.connect() as conn:
        return store.current_figures(conn, deps.run_id, deps.entity)


def _blank_mandatory(deps: FiguresDeps) -> list[str]:
    """Face lines the filing requires that hold nothing this year. Required
    totals are left out: they follow their lines, and the checks cover them."""
    filled = {uuid for (uuid, period), r in _current(deps).items() if period == "CY" and r["value"] is not None}
    return [f"{f.id} {f.name}" for f in deps.outline.fields.values()
            if deps.owns(f) and f.on_face and f.mandatory and f.kind == LINE
            and f.concept_uuid not in filled]


def check_pages(run_id: int, checks: list[dict]) -> list[int]:
    """The printed pages of the figures the checks needing action point at."""
    with db.connect() as conn:
        return figure_pages(conn, run_id, [(c.get("target_concept_uuid"), c.get("period"), c.get("entity_scope"))
                                           for c in checks])


def comparatives(deps: FiguresDeps) -> tuple[list[str], list[str]]:
    """Last year's figures kept from the starting workbook on this agent's own fields: (the one action, when
    some are not compared with the report yet; the differences still open, which only a person decides and
    so never hold up the finish)."""
    with db.connect() as conn:
        items = comparisons(conn, deps.family, deps.entity)
    mine = [(f, i) for f, i in ((deps.outline.for_uuid(i["concept_uuid"]), i) for i in items) if deps.owns(f)]
    if not mine:
        return [], []
    todo = [f"{f.id} {f.name}" for f, i in mine if i["report_value"] is None]
    action = [] if not todo else [
        f"Last year's figures kept from the workbook: {len(todo)} of {len(mine)} are not compared with the report "
        f"yet ({', '.join(todo[:10])}{', …' if len(todo) > 10 else ''}). Save last year's amount as printed for "
        "each; when the report does not show one, say so in unresolved."]
    by_id = {i["id"]: f for f, i in mine}
    differences = [
        f"{by_id[i['id']].id} {by_id[i['id']].name}: the workbook holds {fmt_amount(float(i['value']))}, you read "
        f"{fmt_amount(float(i['disputed_value'] if i['sign_open'] else i['report_value']))}"
        + (" (the opposite sign)." if i["sign_open"] else ".")
        for i in open_differences([i for _f, i in mine], DEFAULT_TOLERANCE)]
    return action, differences


def run_checks(ctx: RunContext[FiguresDeps]) -> str:
    """Run the template's checks on what is saved now: the balance, printed totals against what
    the template adds up, and the required fields still blank."""
    deps = ctx.deps
    with db.connect() as conn:
        results = [c for c in read_checks(conn, deps.run_id) if c["entity_scope"] == deps.entity
                   and _relevant(deps, c["name"]) and c["status"] != "not_applicable" and c["name"] != COMPARATIVES]
    compare_action, differences = comparatives(deps)
    action = [f"{c['title']}: {c['message']}" for c in results if c["status"] in ACTION] + compare_action
    waiting = [f"{c['title']}: {c['message']}" for c in results if c["status"] == "not_assessed"]
    passed = [f"{c['title']}: {c['message']}" for c in results if c["status"] == "passed"]
    blank = _blank_mandatory(deps)
    deps.checked_at, deps.checks_open = deps.writes, action
    out = ["Action required:", *[f"- {a}" for a in action]] if action else ["Nothing needs action."]
    if waiting:
        out += ["Not assessed yet:", *[f"- {w}" for w in waiting]]
    if differences:
        out += ["For information, last year's figures that differ from the workbook (a person decides; the kept "
                "figure stays, so there is nothing to fix):", *[f"- {d}" for d in differences]]
    if blank:
        out += ["For information, required fields blank this year (blank is right when the report does not "
                "show it):", *[f"- {b}" for b in blank]]
    if passed:
        out += ["Passed:", *[f"- {p}" for p in passed]]
    deps.event("checked", f"Checks: {len(action)} need action, {len(passed)} passed.",
               {"action": len(action), "passed": len(passed), "blank_required": len(blank)},
               check_pages(deps.run_id, [c for c in results if c["status"] in ACTION]))
    return "\n".join(out)


def _problems(deps: FiguresDeps, report: list[CoverageLine]) -> list[str]:
    out = []
    held = {uuid for (uuid, _), r in _current(deps).items()
            if r["value"] is not None or r["stated_value"] is not None}
    for line in report:
        if line.action == "skipped" and not line.reason.strip():
            out.append(f"{line.label!r} is skipped with no reason; give one.")
        if line.action == "written" and not line.fields:
            out.append(f"{line.label!r} is written, so name the field ids it went into.")
        for fid in line.fields:
            f = deps.outline.get(fid)
            if not deps.owns(f):
                out.append(f"{line.label!r} names {fid}, which is not a field id in the outline.")
            elif f.concept_uuid not in held:
                out.append(f"{line.label!r} names {f.id} {f.name}, but nothing is saved there.")
    return out


def _face_of(deps: FiguresDeps, field_id: str):
    """The face field a field ends up in: itself if on the face, else the nearest total above it on the face."""
    f, seen = deps.outline.get(field_id), set()
    while f is not None and not f.on_face and f.parent and f.id not in seen:
        seen.add(f.id)
        f = deps.outline.get(f.parent)
    return f if f is not None and f.on_face else None


def shared_face_fields(deps: FiguresDeps, lines: list[CoverageLine]) -> list[str]:
    """Advice, never a refusal: separately printed lines that all end up in one face field.
    Right when the template's face is coarser than the report's; wrong when one of them has a
    face field of its own (v2 live run, 18 November 2026: a separately printed line was folded
    into payables, and no check can see it because the total stays the same)."""
    by_face: dict[str, list[str]] = {}
    for line in lines:
        if line.action != "written" or line.page not in deps.statement_pages:
            continue
        faces = {face.id for face in (_face_of(deps, fid) for fid in line.fields) if face is not None}
        for face_id in faces:
            by_face.setdefault(face_id, []).append(line.label)
    out = []
    for face_id, labels in by_face.items():
        if len(set(labels)) > 1:
            face = deps.outline.get(face_id)
            out.append(f"{', '.join(repr(x) for x in dict.fromkeys(labels))} are printed as separate lines but all "
                       f"end up in {face.id} {face.name}. That is right when the template has no face field of their "
                       "own; check whether one of them has.")
    return out


def report_coverage(ctx: RunContext[FiguresDeps], lines: list[CoverageLine]) -> str:
    """Account for every printed line of the statements you fill: written (with the field ids) or skipped
    (with the reason). Report every line each time; the last report counts."""
    return _coverage(ctx.deps, lines)


def statements_of(deps: FiguresDeps, line: CoverageLine) -> set[str]:
    """The statements a coverage line is for: those of the fields it names (a line on a page that holds two
    statements may name fields of both), else those printed on its page."""
    named = {f.statement for f in (deps.outline.get(fid) for fid in line.fields) if deps.owns(f)}
    return named or {s for s in deps.statements if line.page in deps.pages_of.get(s, [])}


def _per_statement(deps: FiguresDeps, printed: list, missing: list) -> list[str]:
    """One line per statement filled: how many of its printed lines are accounted for."""
    out = []
    for statement in deps.statements:
        pages = set(deps.pages_of.get(statement, []))
        mine = [p for p in printed if p.page in pages]
        open_here = [m for m in missing if m.page in pages]
        out.append(f"- {statement}: {len(mine) - len(open_here)} of {len(mine)} printed lines accounted for."
                   if mine else f"- {statement}: the code found no table lines on its pages; your report is kept.")
    return out


def _coverage(deps: FiguresDeps, lines: list[CoverageLine]) -> str:
    printed = coverage.printed_lines(deps.contents, deps.statement_pages)
    missing = coverage.unaccounted(printed, lines)
    problems = _problems(deps, lines)
    deps.coverage = [line.model_dump() for line in lines]
    deps.covered = {s for line in lines for s in statements_of(deps, line)}
    deps.coverage_open = [coverage.describe(m, printed) for m in missing] + problems
    deps.coverage_at = deps.writes
    written = sum(1 for line in lines if line.action == "written")
    deps.event("coverage", f"Coverage: {written} printed line(s) written, {len(lines) - written} skipped, "
                           f"{len(deps.coverage_open)} still open.",
               {"written": written, "skipped": len(lines) - written, "open": len(deps.coverage_open)})
    advice = shared_face_fields(deps, lines)
    if not printed:
        head = ("The code found no table lines on the statement pages to compare with, so your report is kept "
                "as given.")
    elif not deps.coverage_open:
        head = f"Every printed line is accounted for: {written} written, {len(lines) - written} skipped."
    else:
        head = f"{len(printed) - len(missing)} of {len(printed)} printed lines are accounted for."
    out = [head]
    if len(deps.statements) > 1 and printed:
        out += _per_statement(deps, printed, missing)
    if missing:
        out += ["Not accounted for yet:", *[f"- {coverage.describe(m, printed)}" for m in missing]]
    if problems:
        out += ["To correct:", *[f"- {p}" for p in problems]]
    if advice:
        out += ["To look at once (advice):", *[f"- {a}" for a in advice]]
    return "\n".join(out)


class FinishReport(BaseModel):
    summary: str = Field(description="A few sentences: what you saved and how you checked it.")
    unresolved: list[str] = Field(default_factory=list,
                                  description="Each point left open, one sentence each with its reason.")


def _reasons(deps: FiguresDeps) -> list[str]:
    out = []
    if deps.writes == 0:
        out.append("No figure is saved yet: save the statement's figures with save_figures.")
    elif deps.checked_at != deps.writes:
        out.append("Run the checks with run_checks after your last change.")
    if deps.coverage_open is None:
        out.append("Account for every printed line with report_coverage.")
    elif deps.coverage_at != deps.writes:
        out.append("Figures changed since your last report_coverage, so report coverage again.")
    elif deps.coverage_open:
        out.append(f"Coverage leaves {len(deps.coverage_open)} point(s) open; see the last report_coverage result.")
    if deps.checked_at == deps.writes and deps.checks_open:
        out.append("These checks still need action: " + " ".join(deps.checks_open))
    return out


def _only_checks_open(deps: FiguresDeps) -> bool:
    """Saved, checked and covered after the last change, with only failing checks left."""
    return (deps.writes > 0 and deps.checked_at == deps.writes and bool(deps.checks_open)
            and deps.coverage_at == deps.writes and deps.coverage_open == [])


def finish(ctx: RunContext[FiguresDeps], report: FinishReport) -> FinishReport:
    """The run ends only with the work checked and accounted for, or honestly left open."""
    deps = ctx.deps
    reasons = _reasons(deps)
    last_step = ctx.run_step >= deps.max_steps
    only_checks = _only_checks_open(deps)
    honest = bool(report.unresolved) and (deps.refused_finish or only_checks)
    if reasons and not honest and not last_step:
        deps.refused_finish = True
        deps.event("notice", "The finish was sent back: " + reasons[0])
        raise ModelRetry("Not finished yet:\n" + "\n".join(f"- {r}" for r in reasons) + "\nFix these. If one "
                         "cannot be fixed because of what the report shows, finish again and list each open point "
                         "in unresolved with its reason.")
    deps.finish = {**report.model_dump(), "open_when_finished": reasons, "at_last_step": last_step and bool(reasons)}
    return report

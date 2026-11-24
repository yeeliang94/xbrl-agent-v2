"""The Reviewer: works one correction round through the shared agent loop.

It starts from the saved figures, the pages and the round's comments, in a
review packet built here, so a round works days after extraction. Its tools
are the page tools, the figures agent's field and outline tools, its own
save, clear and move (the same store, tagged with the round), run_checks,
answer_comment and leave_comment, and on a run with notes the note tools
(`note_tools.py`). The finish is checked by
`tools.finish`.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from app import db
from app.agents import history, loop, pages, workbench
from app.catalog.lookup import run_family
from app.catalog.note_fields import run_note_fields
from app.documents import store as documents
from app.extraction import outline as outline_mod, outline_text, tools as figure_tools
from app.scope.fields import names_of, statement_words
from app.extraction.state import budgeted
from app.figures.sums import fmt_amount
from app.guidance import framing
from app.reading import store as reading
from app.notes.state import PROSE_STATEMENT, notes_outline
from app.notes import store_reports
from app.review import changes, instructions, leave, note_figure_tools, note_tools, tools
from app.review.state import ACTOR, NAME, ReviewDeps, round_statements

MAX_STEPS = 40
MAX_SECONDS = 20 * 60
THINKING = "medium"
PICTURE_BUDGET = 12
PICTURE_TOOLS = history.PICTURE_TOOLS | {"preview_notes"}
TOOLS = (*pages.PAGE_TOOLS, figure_tools.find_fields, figure_tools.show_section, figure_tools.lookup_definitions,
         figure_tools.add_up, tools.save_figures, tools.clear_figures, tools.move_figures, tools.run_checks,
         tools.answer_comment, leave.leave_comment)
TEXT_TOOLS = frozenset({"read_pages", "search_pages", "find_fields", "show_section", "lookup_definitions",
                        "show_notes", "find_note_fields"})
PERIOD_WORDS = {"CY": "this year", "PY": "last year"}


class CannotStart(ValueError):
    """The round has nothing the Reviewer can work on. `str()` is one plain sentence."""


def _statements(family, comments: list[sqlite3.Row]) -> tuple[str, ...]:
    """The statements the Reviewer works on (`state.round_statements`)."""
    found = round_statements(family, comments)
    if not found:
        raise CannotStart("No statement is part of this run, so there is nothing to correct yet.")
    return found


def _saved_lines(conn: sqlite3.Connection, run_id: int, figure_ids: list[int], deps: ReviewDeps) -> list[str]:
    out = []
    for fid in figure_ids:
        row = conn.execute("SELECT * FROM figures WHERE id = ?", (fid,)).fetchone()
        f = deps.outline.for_uuid(row["concept_uuid"])
        name = f"{f.id} {f.name}" if f else row["concept_uuid"]
        value = None if row["status"] == "not_disclosed" else row["value"]
        lines = conn.execute("SELECT printed_label, page, amount FROM figure_lines WHERE figure_id = ? ORDER BY id",
                             (fid,)).fetchall()
        source = "; ".join(f"{line['printed_label']!r} on page {line['page']}"
                           + (f" ({fmt_amount(line['amount'])})" if line["amount"] is not None else "")
                           for line in lines) or "no printed line"
        out.append(f"Saved now: {name} {row['period']} {'blank' if value is None else fmt_amount(value)}, "
                   f"from {source}. Certainty {row['certainty']}"
                   + (f", reason: {row['reason']}" if row["reason"] else "") + ".")
    return out


def _report_where(conn: sqlite3.Connection, deps: ReviewDeps, report_id: int) -> str:
    """A comment on one of the notes agent's reports: what it reported, with the field's id for the note tools."""
    found = next((r for r in store_reports.public_reports(conn, deps.run_id) if r["id"] == report_id), None)
    if found is None:
        return "the notes as a whole (the report it was about is gone)"
    fid = getattr(deps.outline, "note_ids", {}).get(found["node_uuid"]) if found["node_uuid"] else None
    what = (f"the field {fid} {found['field_label']}" if fid else found["field_label"]) or (
        f"note {found['note_number']}" if found["note_number"] else "the notes")
    kinds = {"missing_mandatory_field": "a required field no note fills", "source_gap": "a capture problem",
             "routed_elsewhere": "a note placed in another template"}
    return (f"{what}, which the notes agent reported as {kinds.get(found['kind'], 'a report')} "
            f"({found['status']}): {found['reason']}")


def _where(c: sqlite3.Row, deps: ReviewDeps, conn: Optional[sqlite3.Connection] = None) -> str:
    if c["target_kind"] == "statement" and c["statement"] == PROSE_STATEMENT:
        if c["report_id"] and conn is not None:
            return _report_where(conn, deps, int(c["report_id"]))
        return "the notes as a whole"
    if c["target_kind"] == "statement":
        return f"the whole {statement_words(c['statement'], deps.family.variants.get(c['statement']))}"
    f = deps.outline.for_uuid(c["concept_uuid"])
    name = f"{f.id} {f.name} ({' › '.join(f.path) or 'top level'})" if f else "a field outside the outline"
    entity = c["entity_scope"] or "Company"
    if c["dimension_key"]:   # a share class or related-party category, by its member as save_note_figures takes it
        members = json.loads(c["dimension_key"]).values()
        name += f", category {', '.join(m.split('_', 1)[-1] for m in members)}"
    if c["target_kind"] == "line":
        return f"{name}, {entity} figures, every year"
    return f"{name}, {entity} figures, {PERIOD_WORDS.get(c['period'], c['period'])} ({c['period']})"


def build_deps(round_row: sqlite3.Row, *, job_id: Optional[int] = None, max_steps: int = MAX_STEPS
               ) -> tuple[ReviewDeps, str]:
    run_id, round_id = int(round_row["run_id"]), int(round_row["id"])
    with db.connect() as conn:
        family = run_family(conn, run_id)
        if family is None:
            raise CannotStart("There is no such run.")
        statements = _statements(family, changes.round_comments(conn, round_id))
        path, total = documents.pdf_path(conn, run_id)
        run = conn.execute("SELECT r.standard, c.name AS company, s.unit, s.year_end FROM runs r "
                           "LEFT JOIN companies c ON c.id = r.company_id LEFT JOIN run_setup s ON s.run_id = r.id "
                           "WHERE r.id = ?", (run_id,)).fetchone()
        pages_of = {r["statement"]: json.loads(r["pages_json"]) for r in conn.execute(
            "SELECT statement, pages_json FROM run_statements WHERE run_id = ?", (run_id,))
            if r["statement"] in statements}
        notes = [dict(r) for r in conn.execute("SELECT number, title, first_page, last_page FROM run_notes "
                                               "WHERE run_id = ? ORDER BY position", (run_id,))]
        numeric = conn.execute(
            "SELECT 1 FROM round_comments rc JOIN comments c ON c.id = rc.comment_id WHERE rc.round_id = ? "
            "AND c.statement IN ('ISSUED_CAPITAL', 'RELATED_PARTY') LIMIT 1", (round_id,)).fetchone() is not None
        outline = (outline_mod.build_with_numeric_notes if numeric else outline_mod.build)(conn, family)
        has_notes = conn.execute("SELECT 1 FROM notes WHERE run_id = ? LIMIT 1", (run_id,)).fetchone() is not None
        if has_notes:   # note fields by id, and readable() names them for a person
            outline = notes_outline(outline, run_note_fields(conn, run_id))
        deps = ReviewDeps(run_id=run_id, pdf_path=str(path), page_count=total,
                          contents=reading.page_contents(conn, run_id), family=family, outline=outline,
                          statements=statements,
                          statement_pages=sorted({p for s in statements for p in pages_of.get(s, [])}),
                          pages_of=pages_of,
                          max_steps=max_steps, job_id=job_id, actor_name=ACTOR, source=NAME, round_id=round_id,
                          round_number=int(round_row["number"]),
                          checks_before=json.loads(round_row["checks_before_json"] or "[]"), has_notes=has_notes, numeric=numeric)
        packet = []
        for c in changes.round_comments(conn, round_id):
            deps.comment_ids.append(c["id"])
            deps.scopes[c["id"]] = c["scope"]
            deps.entities[c["id"]] = c["entity_scope"] if c["target_kind"] in ("figure", "line") else None
            if c["status"] == "answered":
                deps.answered[c["id"]] = c["outcome"]
            if c["target_kind"] == "note":
                where, saved = note_tools.packet_where(conn, deps, c)
            else:
                where = _where(c, deps, conn)
                saved = _saved_lines(conn, run_id, changes.own_figures(conn, c), deps) or (
                    ["Saved now: nothing."] if c["target_kind"] != "statement" else [])
            packet.append({"id": c["id"], "author": c["author_name"], "scope": c["scope"], "where": where,
                           "saved": saved, "thread": json.loads(c["thread_json"] or "[]"), "text": c["text"]})
        placed = note_tools.placed_lines(conn, deps) if has_notes else []
        failing = [f"{r['check_name']} ({r['entity_scope']}): {r['message']}" for r in conn.execute(
            "SELECT check_name, entity_scope, message FROM check_results WHERE run_id = ? AND status = 'failed' "
            "ORDER BY check_name", (run_id,))]
    if not deps.comment_ids:
        raise CannotStart("This round has no comments.")
    message = instructions.first_message(
        round_number=deps.round_number, company=run["company"] or "the company", year_end=run["year_end"] or "",
        standard=run["standard"], unit=run["unit"], page_count=total, statement_name=names_of(statements, family.variants),
        entities=family.entity_scopes,
        statement_pages=deps.statement_pages, notes=notes, comments=packet, failing=failing,
        outline_text="\n\n".join([outline_text.render(outline, s) for s in statements] + (
            [outline_text.render(outline, s) for s in note_figure_tools.figure_tools.NUMERIC if outline.roots.get(s)]
            + ["Share capital and related-party categories, by member name:",
               *note_figure_tools.figure_tools.category_lines(family.standard)] if numeric else [])),
        placed_notes=placed)
    return deps, message


def spec(model_id: str, bench: workbench.Workbench, deps: ReviewDeps, max_steps: int = MAX_STEPS,
         guidance: str = "") -> loop.AgentSpec:
    trimmer = history.Trimmer(text_tools=TEXT_TOOLS, saved=lambda _messages: deps.writes > 0,
                              picture_tools=PICTURE_TOOLS, picture_budget=PICTURE_BUDGET)
    given = (*TOOLS, *(note_tools.TOOLS if deps.has_notes else ()), *(note_figure_tools.TOOLS if deps.numeric else ()))
    return loop.AgentSpec(name=NAME, model_id=model_id,
                          instructions=instructions.instructions(bench.on, bench.why, guidance, notes=deps.has_notes,
                                                                numeric=deps.numeric),
                          tools=[budgeted(t) for t in given], output_type=tools.ReviewFinish, max_steps=max_steps,
                          max_seconds=MAX_SECONDS, retries=4, thinking=THINKING, code_tool=bench.on,
                          history_processor=trimmer, output_validator=tools.finish)


async def run_reviewer(round_row: sqlite3.Row, model_id: str, *, job_id: Optional[int] = None, model: Any = None,
                       max_steps: int = MAX_STEPS, should_stop=lambda: False
                       ) -> tuple[loop.AgentOutcome, ReviewDeps]:
    deps, message = build_deps(round_row, job_id=job_id, max_steps=max_steps)
    bench = workbench.decide(model_id)
    guidance = framing.prepare(deps.run_id, "round", deps.round_id)
    outcome = await loop.run_agent(spec(model_id, bench, deps, max_steps, guidance), message, deps=deps,
                                   run_id=deps.run_id, job_id=job_id, should_stop=should_stop, model=model,
                                   readable=deps.outline.readable)
    return outcome, deps

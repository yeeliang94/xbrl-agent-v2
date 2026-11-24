"""The notes agent: places the run's notes in the note templates, sets their
look, previews them, and saves the share capital and related-party figures.
Runs through the shared agent loop in sessions (`SESSIONS`), each its own
agent with its own transcript; `app/notes/job.py` runs them side by side.

- placing: places every note across every template. Its first message holds
  every note's text with block ids and each note's candidate fields from
  every template. Its finish checks coverage by source blocks.
- look: a formatting session on its own group of notes (`briefing.look_groups`):
  set_look, preview_note, flag_formatting. It places nothing.
- numeric: the share capital and related-party figures. It places nothing.

Each tool has the step budget note. A session ends through `coverage.finish`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from pydantic_ai import RunContext

from app import db
from app.agents import history, loop, pages, workbench
from app.catalog.lookup import run_family
from app.catalog.note_fields import run_note_fields
from app.documents import store as documents
from app.extraction import outline as outline_mod, outline_text
from app.extraction.agent import _answers
from app.extraction.state import budgeted
from app.guidance import framing
from app.notes import briefing, coverage, figure_tools, instructions, look_tools, tools
from app.notes.state import NAME, PROSE_STATEMENT, NotesDeps, notes_outline
from app.reading import store as reading
from app.review import leave
from app.scope import ask

SESSIONS = ("placing", "numeric", "look")
MAX_STEPS = {"placing": 60, "numeric": 40, "look": 30}
MAX_SECONDS = 30 * 60
THINKING = {"placing": "medium", "numeric": "medium", "look": "low"}   # judging the look needs less
PICTURE_BUDGET = 12
# The sessions that may do arithmetic or checks in the code workbench. The look session only sets formatting.
WORKBENCH_SESSIONS = frozenset({"placing", "numeric"})
ASKED_STOP = "Stopped to ask a person about the scope."
TEXT_TOOLS = frozenset({"read_pages", "search_pages", "show_note_source", "find_note_fields", "show_note_fields",
                        "lookup_definitions", "list_notes"})
PICTURE_TOOLS = history.PICTURE_TOOLS | {"preview_note"}


class CannotStart(ValueError):
    """The run has nothing this agent can work on. `str()` is one plain sentence."""


def leave_comment(ctx: RunContext[NotesDeps], comments: list[leave.AgentComment]) -> str:
    """Leave a comment for a person: on a share capital or related-party figure or line (its field id, with
    the year for one figure), or on the notes as a whole (leave field out, or give a note field id and the
    comment is filed on the notes, naming the field). Something they should look at that you did not change.
    Up to 10 at a time."""
    deps = ctx.deps
    groups: dict[str, list[leave.AgentComment]] = {}
    for c in comments:
        note_field = deps.outline.note_field(c.field) if c.field else None
        if note_field is not None:
            c = c.model_copy(update={"field": None, "period": None, "text": f"{note_field.label}: {c.text}"})
        f = deps.outline.get(c.field) if c.field else None
        groups.setdefault(f.statement if f is not None else PROSE_STATEMENT, []).append(c)
    out = []
    try:
        for statement, group in groups.items():
            deps.statement = statement
            out.append(leave.leave_comment(ctx, group))
    finally:
        deps.statement = PROSE_STATEMENT
    return "\n".join(out) or "Give at least one comment."


_COMMON = (*pages.PAGE_TOOLS, tools.list_notes, tools.show_note_source, coverage.report_gap, leave_comment,
           ask.ask_scope)
TOOLS = {
    "placing": (*_COMMON, tools.find_note_fields, tools.show_note_fields, tools.lookup_definitions,
                tools.place_note, coverage.report_missing_field, coverage.report_coverage),
    "look": (*_COMMON, tools.show_note_fields, look_tools.set_look, look_tools.preview_note,
             look_tools.flag_formatting),
    "numeric": (*_COMMON, tools.find_note_fields, tools.show_note_fields, tools.lookup_definitions,
                coverage.report_missing_field, figure_tools.save_figures, figure_tools.clear_figures),
}


def _standing(conn, deps: NotesDeps) -> list[str]:
    found = coverage.status(conn, deps)
    return [line for line in found.lines if "not placed or reported yet" not in line] + found.reports


def _sections(conn, deps: NotesDeps, family) -> list[tuple[str, str]]:
    if deps.session == "look":
        return [("Your notes, as placed (note id, field, and their blocks; tables row by row from 1):",
                 briefing.group_text(conn, deps))]
    out = []
    if deps.session == "placing":
        lines = [tools.field_line(deps, f) for f in deps.outline.notes.values() if not f.heading]
        out += [("The note fields of every template (id, template, place under its headings):", "\n".join(lines)),
                ("Each note's likely fields from every template, with their official meanings (a search on its "
                 "title, so a starting point):", "\n".join(briefing.candidate_lines(deps)))]
    else:
        outline = deps.outline
        out += [("The share capital and related-party sheets:",
                 "\n\n".join(outline_text.render(outline, s) for s in figure_tools.NUMERIC if outline.roots.get(s))),
                ("Categories each sheet takes (member names for save_figures):",
                 "\n".join(figure_tools.category_lines(family.standard)))]
    out.append(("Each listed note's transcribed text, as show_note_source gives it (block ids for place_note; a "
                "block already placed says where):", briefing.notes_text(conn, deps)))
    return out


def build_deps(run_id: int, session: str, *, job_id: Optional[int] = None, previews: Optional[dict] = None,
               max_steps: Optional[int] = None, group: tuple[int, ...] = (), name: Optional[str] = None
               ) -> tuple[NotesDeps, str]:
    with db.connect() as conn:
        family = run_family(conn, run_id)
        if family is None or not family.standard:
            raise CannotStart("The run's setup is not confirmed, so there are no note templates.")
        path, total = documents.pdf_path(conn, run_id)
        run = conn.execute("SELECT r.standard, r.level, c.name AS company, s.unit, s.year_end FROM runs r "
                           "LEFT JOIN companies c ON c.id = r.company_id LEFT JOIN run_setup s ON s.run_id = r.id "
                           "WHERE r.id = ?", (run_id,)).fetchone()
        notes_list = [dict(r) for r in conn.execute("SELECT number, title, first_page, last_page FROM run_notes "
                                                    "WHERE run_id = ? ORDER BY position", (run_id,))]
        outline = notes_outline(outline_mod.build_numeric_notes(conn, family), run_note_fields(conn, run_id))
        deps = NotesDeps(run_id=run_id, pdf_path=str(path), page_count=total,
                         contents=reading.page_contents(conn, run_id), family=family, outline=outline,
                         session=session, name=name or session, max_steps=max_steps or MAX_STEPS[session],
                         job_id=job_id, notes_list=notes_list, group=frozenset(group),
                         previews=previews if previews is not None else {})
        standing = _standing(conn, deps) if session != "look" else []
        answers = [{"question": r["question"], "answer": r["answer_text"] or r["label"],
                    "setup_changed": bool(r["setup_changed"])} for r in _answers(conn, run_id)]
        sections = _sections(conn, deps, family)
    message = instructions.first_message(
        session=session, company=run["company"] or "the company", year_end=run["year_end"] or "",
        standard=run["standard"], level=deps.entity, unit=run["unit"], page_count=total, notes=notes_list,
        standing=standing, sections=sections, answers=answers)
    return deps, message


def spec(model_id: str, deps: NotesDeps, guidance: str = "",
         bench: workbench.Workbench = workbench.Workbench(False, "")) -> loop.AgentSpec:
    trimmer = history.Trimmer(text_tools=TEXT_TOOLS, saved=lambda _messages: deps.writes > 0,
                              picture_tools=PICTURE_TOOLS, picture_budget=PICTURE_BUDGET)
    return loop.AgentSpec(name=NAME, model_id=model_id,
                          instructions=instructions.instructions(deps.session, guidance, workbench_on=bench.on),
                          tools=[budgeted(t) for t in TOOLS[deps.session]],
                          output_type=coverage.FinishReport, max_steps=deps.max_steps, max_seconds=MAX_SECONDS,
                          retries=4, thinking=THINKING[deps.session], code_tool=bench.on, history_processor=trimmer,
                          output_validator=coverage.finish)


def open_question(run_id: int) -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM scope_questions WHERE run_id = ? AND status = 'open'",
                            (run_id,)).fetchone() is not None


async def run_session(run_id: int, session: str, model_id: str, *, job_id: Optional[int] = None, model: Any = None,
                      previews: Optional[dict] = None, should_stop: Callable[[], Any] = lambda: False,
                      max_steps: Optional[int] = None, group: tuple[int, ...] = (), name: Optional[str] = None
                      ) -> tuple[loop.AgentOutcome, NotesDeps]:
    deps, message = build_deps(run_id, session, job_id=job_id, previews=previews, max_steps=max_steps, group=group,
                               name=name)
    guidance = framing.prepare(run_id, "notes")
    bench = workbench.decide(model_id, wanted=session in WORKBENCH_SESSIONS)
    deps.event("workbench", bench.why, {"on": bench.on, "session": deps.name})

    def stop() -> Any:
        if deps.asked is not None or open_question(run_id):   # this agent's question, or the figures agent's
            return ASKED_STOP
        return should_stop()

    outcome = await loop.run_agent(spec(model_id, deps, guidance, bench), message, deps=deps, run_id=run_id, job_id=job_id,
                                   model=model, readable=deps.outline.readable, should_stop=stop)
    return outcome, deps


def record(outcome: loop.AgentOutcome, deps: NotesDeps) -> dict:
    return {"session": deps.name, "kind": deps.session, "notes": sorted(deps.group), "status": outcome.status, "message": outcome.message, "steps": outcome.steps,
            "finish": deps.finish, "coverage_open": deps.coverage_open, "writes": deps.writes,
            "previews": {str(k): v for k, v in deps.previews.items()},
            "code_used": outcome.code_tool_used,
            "transcript": outcome.transcript_path.name if outcome.transcript_path else None,
            "tool_errors": outcome.tool_errors}


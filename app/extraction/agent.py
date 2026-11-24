"""The figures agent: fills one statement into its template, or several in
one run (step 7d), for one entity's columns (Group or Company), saving by
field id through the figure store. Runs through the shared agent loop.

Tools: the shared page tools, find_fields, show_section, lookup_definitions,
save_figures, clear_figures, add_up, run_checks, report_coverage,
leave_comment (a point for a person, shared with the Reviewer) and
ask_scope (a scope question; the run stops after it), each with the step
budget note. The code workbench is given when
`app/agents/workbench.decide` allows it. The run ends through the finish
check in `checking.finish`.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional, Sequence

from app import db
from app.agents import history, loop, pages, workbench
from app.catalog.lookup import run_family
from app.catalog.statements import StatementType
from app.documents import store as documents
from app.extraction import checking, instructions, outline as outline_mod, outline_text, tools
from app.extraction.state import COMPANY, NAME, FiguresDeps, budgeted
from app.guidance import framing
from app.figures import store
from app.figures.sums import fmt_amount
from app.reading import store as reading
from app.reading.map_schema import STATEMENTS, statement_name
from app.review import leave
from app.scope import ask, fields

MAX_STEPS = 60
MAX_SECONDS = 30 * 60
# One agent filling several statements (step 7d) gets this much more for each statement after the first: less
# than a run of its own, since the document is read once and the notes are shared, up to the shared loop's
# ceiling of 120 steps (5 statements: 120 steps, 110 minutes).
EXTRA_STEPS = 45
EXTRA_SECONDS = 20 * 60
THINKING = "medium"
PICTURE_BUDGET = 12
TOOLS = (*pages.PAGE_TOOLS, tools.find_fields, tools.show_section, tools.lookup_definitions, tools.save_figures,
         tools.clear_figures, tools.add_up, checking.run_checks, checking.report_coverage, leave.leave_comment,
         ask.ask_scope)
TEXT_TOOLS = frozenset({"read_pages", "search_pages", "find_fields", "show_section", "lookup_definitions"})
NAMES = fields.STATEMENT_WORDS


ASKED_STOP = "Stopped to ask a person about the scope."


class CannotStart(ValueError):
    """The run has nothing this agent can fill. `str()` is one plain sentence."""


def limits(count: int) -> tuple[int, int]:
    """The step and time limits of one run filling `count` statements."""
    extra = max(count, 1) - 1
    return min(MAX_STEPS + EXTRA_STEPS * extra, loop.MAX_STEPS_CEILING), MAX_SECONDS + EXTRA_SECONDS * extra



def build_deps(run_id: int, statements: str | Sequence[str], *, entity: str = COMPANY, filled: Sequence[str] = (),
               job_id: Optional[int] = None, max_steps: Optional[int] = None) -> tuple[FiguresDeps, str]:
    """The tools' shared state and the opening message, from the confirmed setup. `statements` is one
    statement or several for one agent; `filled` the statements finished before this run (`progress.finished`),
    whose checks across statements this run then sees."""
    wanted = (statements,) if isinstance(statements, str) else tuple(dict.fromkeys(statements))
    with db.connect() as conn:
        family = run_family(conn, run_id)
        missing = [s for s in wanted if family is None or StatementType(s) not in family.template_ids]
        if missing or not wanted:
            raise CannotStart(f"The {NAMES[missing[0]] if missing else 'statement'} is not part of this run.")
        if entity not in family.entity_scopes:
            raise CannotStart(f"This run has no {entity} figures to fill.")
        path, total = documents.pdf_path(conn, run_id)
        run = conn.execute("SELECT r.year, r.standard, r.level, c.name AS company, s.unit, s.year_end FROM runs r "
                           "LEFT JOIN companies c ON c.id = r.company_id LEFT JOIN run_setup s ON s.run_id = r.id "
                           "WHERE r.id = ?", (run_id,)).fetchone()
        printed = {r["statement"]: (json.loads(r["pages_json"]), r["included"], r["variant"]) for r in conn.execute(
            "SELECT statement, variant, included, pages_json FROM run_statements WHERE run_id = ?", (run_id,))}
        notes = [dict(r) for r in conn.execute("SELECT number, title, first_page, last_page FROM run_notes "
                                               "WHERE run_id = ? ORDER BY position", (run_id,))]
        outline = outline_mod.build(conn, family)
        contents = reading.page_contents(conn, run_id)
        several = len(wanted) > 1
        pages_of = {s: printed[s][0] for s in wanted}
        deps = FiguresDeps(run_id=run_id, pdf_path=str(path), page_count=total, contents=contents,
                           family=family, outline=outline, statements=wanted,
                           statement_pages=sorted({p for s in wanted for p in pages_of[s]}),
                           pages_of=pages_of, entity=entity,
                           filled=tuple(s for s in filled if s not in wanted),
                           max_steps=max_steps or limits(len(wanted))[0], job_id=job_id)
        existing = store.current_figures(conn, run_id, deps.entity)
        answers = [{"question": r["question"], "answer": r["answer_text"] or r["label"],
                    "setup_changed": bool(r["setup_changed"])} for r in _answers(conn, run_id)]
    saved, starting = [], []
    for (uuid, period), r in existing.items():
        f = outline.for_uuid(uuid)
        amount = r["value"] if r["value"] is not None else r["stated_value"]
        if f is None or not deps.owns(f) or amount is None or r["origin"] == "calculated":
            continue
        if r["origin"] in ("prior_workbook", "typed_in_workbook"):   # imported, not this agent's work
            starting.append(f"{f.id} {f.name}: {period} {fmt_amount(amount)}"
                            + (" (kept as filed)" if r["origin"] == "prior_workbook" else " (typed, kept fixed)"))
        else:
            saved.append(f"{f.id} {f.name}: {period} {fmt_amount(amount)}")
    # A new attempt after a restart starts from the figures already saved, and every run from the figures
    # imported from a starting workbook (a statement typed in it in full leaves the agent nothing to save):
    # the finish and the job count them, and the checks and coverage are asked for again.
    deps.writes = len(saved) + len(starting)
    others = [f"{statement_name(s, printed[s][2])} on page(s) {', '.join(map(str, printed[s][0]))}" for s in STATEMENTS
              if s in printed and s not in wanted and printed[s][0] and printed[s][2] != "NotPrepared"]
    message = instructions.first_message(
        statement_name=fields.names_of(wanted, family.variants), company=run["company"] or "the company",
        year_end=run["year_end"] or "",
        standard=run["standard"], level=deps.entity, unit=run["unit"], page_count=total,
        statement_pages=deps.statement_pages, other_statements=others, notes=notes,
        outline_text="\n\n".join(outline_text.render(outline, s) for s in wanted), saved=saved, answers=answers,
        starting=starting,
        several=[(fields.statement_words(s, family.variants.get(s)), pages_of[s]) for s in wanted]
        if several else None,
        both_entities=len(family.entity_scopes) > 1)
    return deps, message


def _answers(conn, run_id: int) -> list[dict]:
    """The run's answered scope questions, oldest first, with the label of the choice taken."""
    out = []
    for r in conn.execute("SELECT * FROM scope_questions WHERE run_id = ? AND status = 'answered' ORDER BY id",
                          (run_id,)):
        choices = json.loads(r["choices_json"])
        index = r["answer_choice"]
        out.append({**dict(r), "label": choices[index]["label"] if index is not None else None})
    return out


def _open_question(run_id: int) -> bool:
    """A scope question either agent asked (the notes agent too): both stop and keep their work."""
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM scope_questions WHERE run_id = ? AND status = 'open'",
                            (run_id,)).fetchone() is not None


def spec(model_id: str, bench: workbench.Workbench, deps: FiguresDeps, max_steps: Optional[int] = None,
         guidance: str = "") -> loop.AgentSpec:
    """A fresh spec per run: its history trimmer remembers what it cut. Page
    pictures may be trimmed once a figure is saved."""
    trimmer = history.Trimmer(text_tools=TEXT_TOOLS, saved=lambda _messages: deps.writes > 0,
                              picture_budget=PICTURE_BUDGET)
    steps, seconds = limits(len(deps.statements))
    return loop.AgentSpec(name=NAME, model_id=model_id,
                          instructions=instructions.instructions(bench.on, bench.why, guidance),
                          tools=[budgeted(t) for t in TOOLS],
                          output_type=checking.FinishReport, max_steps=max_steps or steps, max_seconds=seconds,
                          retries=4, thinking=THINKING,
                          code_tool=bench.on, history_processor=trimmer, output_validator=checking.finish)


async def run_figures(run_id: int, statement: str | Sequence[str], model_id: str, *, job_id: Optional[int] = None,
                      model: Any = None, max_steps: Optional[int] = None, entity: str = COMPANY,
                      filled: Sequence[str] = (), should_stop: Callable[[], bool] = lambda: False
                      ) -> tuple[loop.AgentOutcome, FiguresDeps, workbench.Workbench]:
    deps, message = build_deps(run_id, statement, entity=entity, filled=filled, job_id=job_id, max_steps=max_steps)
    bench = workbench.decide(model_id)
    deps.event("workbench", bench.why, {"on": bench.on})
    guidance = framing.prepare(run_id, "extract")
    outcome = await loop.run_agent(spec(model_id, bench, deps, deps.max_steps, guidance), message, deps=deps,
                                   run_id=run_id, job_id=job_id, model=model, readable=deps.outline.readable,
                                   should_stop=lambda: (
                                       ASKED_STOP if deps.asked is not None or _open_question(run_id)
                                       else should_stop()))
    return outcome, deps, bench

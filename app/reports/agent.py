"""The reports agent: one run on the shared agent loop fills the three
reports' fields (`app/reports/tools.py`), with its own transcript.

Its first message holds every field of the three reports with its id and
kind, the pages where the Reader found each report, and the other sections
it mapped (the statutory declaration), whose facts may answer short fields. It finishes through
`tools.finish`, which sends it back once while a field is unassessed.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app import db
from app.agents import history, loop
from app.catalog.reports import REPORTS, SECTION_KINDS, report_fields, report_name
from app.documents import store as documents
from app.extraction.state import budgeted
from app.guidance import framing
from app.reading import store as reading
from app.reports import instructions, tools
from app.reports.tools import ReportsDeps

MAX_STEPS = 40
MAX_SECONDS = 20 * 60
THINKING = "medium"
PICTURE_BUDGET = 12
TEXT_TOOLS = frozenset({"read_pages", "search_pages", "show_blocks", "show_fields"})


class CannotStart(ValueError):
    """The run has nothing this agent can work on. `str()` is one plain sentence."""


def report_sections(conn, run_id: int) -> dict[str, list[tuple[int, int]]]:
    """The page ranges where the Reader found each report, by report. Empty when it found none."""
    doc_map = reading.saved_map(conn, run_id) or {}
    out: dict[str, list[tuple[int, int]]] = {}
    for section in doc_map.get("other_sections") or []:
        report = SECTION_KINDS.get(section.get("kind"))
        if report is not None:
            out.setdefault(report, []).append((int(section["first_page"]), int(section["last_page"])))
    return out


def other_sections(conn, run_id: int) -> list[tuple[str, int, int]]:
    """The other sections the Reader mapped (the statutory declaration and the like) as (title, first, last).
    A short field is answered from whichever page states it, so the agent is told where these are too."""
    doc_map = reading.saved_map(conn, run_id) or {}
    out = []
    for section in doc_map.get("other_sections") or []:
        if SECTION_KINDS.get(section.get("kind")) is None:
            title = section.get("title") or str(section.get("kind") or "").replace("_", " ").capitalize()
            out.append((title, int(section["first_page"]), int(section["last_page"])))
    return out


def _span(a: int, b: int) -> str:
    return f"{a}" if a == b else f"{a}-{b}"


def _section_lines(found: dict[str, list[tuple[int, int]]], others: list[tuple[str, int, int]] = ()) -> list[str]:
    lines = []
    for report in REPORTS:
        spans = found.get(report)
        where = ", ".join(_span(a, b) for a, b in spans) if spans else "not found by the Reader"
        lines.append(f"- {report_name(report)} ({report}): {where}")
    lines += [f"- {title} (not a report to fill, but its facts may answer short fields): {_span(a, b)}"
              for title, a, b in others]
    return lines


def build_deps(run_id: int, *, job_id: Optional[int] = None, max_steps: Optional[int] = None
               ) -> tuple[ReportsDeps, str]:
    with db.connect() as conn:
        run = conn.execute("SELECT r.standard, r.level, c.name AS company, s.year_end FROM runs r "
                           "LEFT JOIN companies c ON c.id = r.company_id LEFT JOIN run_setup s ON s.run_id = r.id "
                           "WHERE r.id = ?", (run_id,)).fetchone()
        if run is None or not run["standard"]:
            raise CannotStart("The run's setup is not confirmed, so there are no reports to fill.")
        try:
            path, total = documents.pdf_path(conn, run_id)
        except Exception as exc:  # noqa: BLE001 - NoDocument and the like
            raise CannotStart("The run has no document, so there are no reports to read.") from exc
        found = report_sections(conn, run_id)
        others = other_sections(conn, run_id)
        deps = ReportsDeps(run_id=run_id, pdf_path=str(path), page_count=total,
                           contents=reading.page_contents(conn, run_id), standard=run["standard"].lower(),
                           job_id=job_id, max_steps=max_steps or MAX_STEPS)
    fields = []
    for report in REPORTS:
        fields.append(f"{report_name(report)} ({report}):")
        fields += [tools.field_line(f) for f in report_fields(report, deps.standard)]
    message = instructions.first_message(
        company=run["company"] or "the company", year_end=run["year_end"] or "", standard=run["standard"],
        level=run["level"] or "", page_count=total, sections=_section_lines(found, others), fields=fields)
    return deps, message


def spec(model_id: str, deps: ReportsDeps, guidance: str = "") -> loop.AgentSpec:
    trimmer = history.Trimmer(text_tools=TEXT_TOOLS, saved=lambda _messages: deps.writes > 0,
                              picture_budget=PICTURE_BUDGET)
    return loop.AgentSpec(name=tools.NAME, model_id=model_id, instructions=instructions.instructions(guidance),
                          tools=[budgeted(t) for t in tools.TOOLS], output_type=tools.FinishReport,
                          max_steps=deps.max_steps, max_seconds=MAX_SECONDS, retries=4, thinking=THINKING,
                          history_processor=trimmer, output_validator=tools.finish)


async def run(run_id: int, model_id: str, *, job_id: Optional[int] = None, model: Any = None,
              should_stop: Callable[[], Any] = lambda: False, max_steps: Optional[int] = None
              ) -> tuple[loop.AgentOutcome, ReportsDeps]:
    deps, message = build_deps(run_id, job_id=job_id, max_steps=max_steps)
    guidance = framing.prepare(run_id, "reports")
    outcome = await loop.run_agent(spec(model_id, deps, guidance), message, deps=deps, run_id=run_id, job_id=job_id,
                                   model=model, should_stop=should_stop)
    return outcome, deps


def record(outcome: loop.AgentOutcome, deps: ReportsDeps) -> dict:
    return {"status": outcome.status, "message": outcome.message, "steps": outcome.steps, "writes": deps.writes,
            "finish": deps.finish, "opened_pages": sorted(deps.opened),
            "transcript": outcome.transcript_path.name if outcome.transcript_path else None,
            "tool_errors": outcome.tool_errors}

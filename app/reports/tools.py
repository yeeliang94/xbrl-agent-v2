"""The reports agent's tools and what they share during one run.

The page tools are the shared ones (`app/agents/pages.py`), wrapped only to
remember which pages the agent opened: a value may cite only a page whose
transcribed words or blocks the agent was shown, or whose picture it saw (v1 `reports/agent.py`:
observed fields need pages the agent inspected). A search names pages but
opens none.

Every refusal is a plain sentence in the tool's result, one per field, so a
batch saves what it can and says what it did not; nothing costs the tool's
retries. The store makes the format checks (`app/reports/store.py`); the
tool adds the agent's own: a known field id, a value with a page, a page the
agent has opened.
"""
from __future__ import annotations

import functools
import inspect
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import BinaryContent, ModelRetry, RunContext

from app import db
from app.agents import pages as page_tools
from app.agents.pages import PageSource
from app.catalog.reports import REPORTS, ReportField, report_fields, report_name
from app.notes import source
from app.reports import store
from app.runs.events import add_event

logger = logging.getLogger(__name__)

NAME = "reports"
MAX_PAGES = 6
MAX_FIELDS = 30


@dataclass
class ReportsDeps(PageSource):
    standard: str = "mfrs"
    job_id: Optional[int] = None
    max_steps: int = 40
    opened: set = field(default_factory=set)        # PDF pages read, listed or seen in this run
    writes: int = 0
    refused_finish: bool = False
    finish: Optional[dict] = None
    warned: set = field(default_factory=set)        # the step budget notes already given
    SOON_NOTE = "Save what is left and finish before they run out."
    LAST_NOTE = "Stop calling tools and finish now: say what you filled and list what is left in unresolved."

    def fields(self) -> dict[str, ReportField]:
        return {f.field_id: f for report in REPORTS for f in report_fields(report, self.standard)}

    def event(self, kind: str, message: str, data: Optional[dict] = None) -> None:
        try:
            add_event(NAME, kind, message, run_id=self.run_id, job_id=self.job_id, data=data)
        except Exception:  # noqa: BLE001 - progress rows never end the work
            logger.warning("Could not record a reports event", exc_info=True)


AGENT = store.Actor("agent", NAME)


# Pages ----------------------------------------------------------------------

def _shown_pictures(result) -> set[int]:
    """The pages a view or zoom actually showed: each picture follows its "PDF page N" caption."""
    shown, caption = set(), None
    for part in result if isinstance(result, list) else ():
        if isinstance(part, str) and part.startswith("PDF page "):
            number = part[len("PDF page "):].split()[0].rstrip(",:")
            caption = int(number) if number.isdigit() else None
        elif isinstance(part, BinaryContent) and caption is not None:
            shown.add(caption)
    return shown


def _read_pages_with_text(deps: ReportsDeps, pages: list[int]) -> set[int]:
    """The pages read_pages gave words for: transcribed and not blank."""
    return {p for p in pages if (deps.contents.get(p) or {}).get("blocks") and not deps.contents[p].get("blank")}


def _opening(tool, limit: int, *, pictures: bool):
    """The shared page tool, remembering only the pages it actually showed: a picture for view and zoom, the
    transcribed words for read. A refusal, or a page with nothing transcribed, opens nothing. Its name, words
    and arguments stay the shared tool's, so the activity rows read the same."""
    @functools.wraps(tool)
    async def run(ctx: RunContext[ReportsDeps], *args, **kwargs):
        result = tool(ctx, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        if pictures:
            ctx.deps.opened.update(_shown_pictures(result))
        else:
            wanted = list(kwargs.get("pages", args[0] if args else None) or [])
            if not page_tools.bad_pages(ctx.deps, wanted, limit):
                ctx.deps.opened.update(_read_pages_with_text(ctx.deps, wanted))
        return result
    return run


view_pages = _opening(page_tools.view_pages, page_tools.MAX_VIEW, pictures=True)
zoom_page = _opening(page_tools.zoom_page, 1, pictures=True)
read_pages = _opening(page_tools.read_pages, page_tools.MAX_READ, pictures=False)
search_pages = page_tools.search_pages


def show_blocks(ctx: RunContext[ReportsDeps], pages: list[int], note: Optional[str] = None) -> str:
    """List the blocks of up to 6 PDF pages with their ids (p12b0, p12b1, ...), for save_narrative. Tables are
    shown row by row.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    problem = page_tools.bad_pages(deps, pages, MAX_PAGES)
    if problem:
        return problem
    out = []
    for page in dict.fromkeys(pages):
        blocks = source.reading_order(deps.contents, page, page)
        if not blocks:
            out.append(f"=== PDF page {page}: no blocks transcribed; view the page to read it.")
            continue
        deps.opened.add(page)
        out.append(f"=== PDF page {page} ({deps.folio(page)}):")
        out += [line for b in blocks for line in source.describe(b)]
    return "\n".join(out)


# Fields ---------------------------------------------------------------------

def field_line(f: ReportField) -> str:
    kind = f"choice of: {'; '.join(f.choices)}" if f.kind == "choice" else \
        {"html": "the report's whole wording (save_narrative)", "date": "date YYYY-MM-DD", "text": "text"}[f.kind]
    return f"- {f.field_id} [{kind}] {f.label}"


def _saved_line(f: ReportField, shown: dict) -> str:
    status = shown["status"]
    if status == "filled":
        value = "wording saved" if f.kind == "html" else repr(shown["value"])
        return f"- {f.field_id} {f.label}: {value} (pages {', '.join(map(str, shown['pages'])) or 'none'})"
    if status == "not_assessed":
        return f"- {f.field_id} {f.label}: not assessed yet"
    return f"- {f.field_id} {f.label}: left empty ({status}): {shown['reason']}"


def show_fields(ctx: RunContext[ReportsDeps], report: Literal["DIRECTORS_REPORT", "STATEMENT_BY_DIRECTORS",
                                                              "AUDITORS_REPORT"],
                note: Optional[str] = None) -> str:
    """What is saved so far for one report's fields, and which are not assessed yet.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    with db.connect() as conn:
        shown = next(r for r in store.run_reports(conn, ctx.deps.run_id) if r["report"] == report)
    by_id = ctx.deps.fields()
    lines = [_saved_line(by_id[f["field_id"]], f) for f in shown["fields"]]
    return f"{report_name(report)}, {shown['assessed']} of {shown['total']} assessed:\n" + "\n".join(lines)


class FieldValue(BaseModel):
    field: str = Field(description="The field id from your first message, such as DIR-7.")
    status: Literal["filled", "not_shown", "unsure"] = Field(
        description="filled with a value; not_shown when the document does not print it; unsure when it cannot "
                    "be read or decided.")
    value: Optional[str] = Field(default=None, description="As printed; a date as YYYY-MM-DD; a choice exactly as "
                                                           "listed. Null when left empty.")
    pages: list[int] = Field(default_factory=list, description="The PDF pages it was read from, opened in this run.")
    reason: str = Field(default="", description="One sentence: what on the page shows it, or why it is left empty.")


def _unopened(deps: ReportsDeps, cited: list[int]) -> list[int]:
    return [p for p in cited if p not in deps.opened]


def save_fields(ctx: RunContext[ReportsDeps], fields: list[FieldValue], note: Optional[str] = None) -> str:
    """Save short fields of any of the three reports, up to 30 at a time: a value with its pages, or the field
    left empty with its reason. A later save of the same field replaces the earlier one. Each line of the
    result says what was saved or why not.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    if not fields:
        return "Give at least one field."
    if len(fields) > MAX_FIELDS:
        return f"Give at most {MAX_FIELDS} fields at a time."
    known = deps.fields()
    out = []
    for item in fields:
        f = known.get("".join(item.field.split()).upper())
        if f is None:
            out.append(f"{item.field}: there is no such field; use an id from your first message, such as DIR-7.")
            continue
        if f.kind == "html" and item.status == "filled":
            out.append(f"{f.field_id}: this is the report's wording, so save it with save_narrative.")
            continue
        if item.status == "filled" and not item.pages:
            out.append(f"{f.field_id}: give the PDF page the value was read from.")
            continue
        missing = _unopened(deps, item.pages)
        if missing:
            out.append(f"{f.field_id}: you have not opened page {missing[0]} in this run, so read or view it first.")
            continue
        write = store.FieldWrite(item.status, item.value if item.status == "filled" else None, (), item.pages,
                                 item.reason)
        out.append(_save(deps, f, write))
    return "\n".join(out)


def save_narrative(ctx: RunContext[ReportsDeps], report: Literal["DIRECTORS_REPORT", "STATEMENT_BY_DIRECTORS",
                                                                 "AUDITORS_REPORT"],
                   blocks: list[str], note: Optional[str] = None) -> str:
    """Save a report's whole wording: its blocks in reading order, as block ids from show_blocks (p12b0) or
    ranges (p12b0-p13b4). Code copies the words; give every block of the report once and nothing of the other
    reports. A later save replaces the earlier one. To leave the wording empty, use save_fields with the
    report's narrative id and status not_shown or unsure.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    f = next(x for x in report_fields(report, deps.standard) if x.kind == "html")
    refs, problem = source.parse_refs(blocks, deps.contents)
    if problem:
        return problem
    if not refs:
        return "Give the report's blocks as ids such as p12b0, or a range such as p12b0-p13b4."
    missing = _unopened(deps, sorted({p for p, _ in refs}))
    if missing:
        return f"You have not opened page {missing[0]} in this run, so list its blocks first."
    return _save(deps, f, store.FieldWrite("filled", None, refs, (), ""))


def _save(deps: ReportsDeps, f: ReportField, write: store.FieldWrite) -> str:
    try:
        with db.connect(immediate=True) as conn:
            saved = store.save_field(conn, deps.run_id, f.report, f.element_id, write, AGENT)
    except store.Refused as exc:
        return f"{f.field_id}: not saved. {exc}"
    deps.writes += 1
    if saved["status"] == "filled":
        shown = "the wording" if f.kind == "html" else repr(saved["value"])
        return f"{f.field_id}: saved {shown}."
    return f"{f.field_id}: left empty ({saved['status']})."


# The finish -------------------------------------------------------------------

class FinishReport(BaseModel):
    summary: str = Field(description="Two or three plain sentences: what you filled.")
    unresolved: list[str] = Field(default_factory=list,
                                  description="Each field a person should look at, by label, with why.")


def finish(ctx: RunContext[ReportsDeps], report: FinishReport) -> FinishReport:
    """The run ends with every field assessed. The agent is sent back once with the fields still unassessed;
    after that, or at the last step, any finish is taken and the unassessed fields stay listed."""
    deps = ctx.deps
    with db.connect() as conn:
        left = store.not_assessed(conn, deps.run_id)
    last_step = ctx.run_step >= deps.max_steps
    if left and not deps.refused_finish and not last_step:
        deps.refused_finish = True
        deps.event("notice", f"The finish was sent back: {len(left)} field(s) are not assessed yet.")
        raise ModelRetry("Not finished yet. These fields are not assessed: "
                         + ", ".join(f"{f.field_id} {f.label}" for f in left[:40])
                         + ". Save each one, or leave it empty with its reason.")
    deps.finish = {**report.model_dump(), "not_assessed": [f.field_id for f in left]}
    return report


TOOLS = (view_pages, zoom_page, read_pages, search_pages, show_blocks, show_fields, save_fields, save_narrative)

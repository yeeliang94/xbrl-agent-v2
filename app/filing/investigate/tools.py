"""The investigating agent's tools: the template toolkit's six scripts on a copy of the template, and
`propose_places`, its one write, into the `placements` table. Hard rules live here and refuse in one plain
sentence: a cell that holds a formula, is locked, already holds a value, was written by the fill, or is
proposed for another figure is never proposed. The agent cannot write a workbook or save a mapping."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from app import db
from app.filing.investigate import store
from app.runs.events import add_event, clean_note
from app.workbook.toolkit import compare as compare_script
from app.workbook.toolkit import find as find_script
from app.workbook.toolkit import identify as identify_script
from app.workbook.toolkit import list_rows as list_script
from app.workbook.toolkit import read as read_script
from app.workbook.toolkit import trial_fill as trial_script
from app.workbook.toolkit.book import Book, NotFound, describe, parse_ref, row_label

logger = logging.getLogger(__name__)

NAME = "investigate"
SOURCE = "fill"


@dataclass
class InvestigateDeps:
    run_id: int
    fill_id: int
    book: Book                        # a copy of the template: the tools read it, none writes it
    filled: Optional[Book]            # the filled file, to compare with
    figures: dict[str, dict]          # "F1" -> the receipt line of a figure the fill could not place
    written: set[str]                 # the cells the fill wrote, as Sheet!E30
    job_id: Optional[int] = None
    max_steps: int = 40
    proposed: dict[str, str] = field(default_factory=dict)    # figure id -> Sheet!E30
    writes: int = 0
    refused_finish: bool = False
    finish: Optional[dict] = None
    warned: set = field(default_factory=set)
    SOON_NOTE = "Propose the places you have found, then finish."
    LAST_NOTE = "Stop calling tools and finish now: list each figure still without a place in not_found."

    def event(self, message: str) -> None:
        try:
            add_event(SOURCE, "investigating", message, run_id=self.run_id, job_id=self.job_id,
                      data={"fill_id": self.fill_id})
        except Exception:  # noqa: BLE001 - progress rows never end the work
            logger.warning("Could not record an investigation event", exc_info=True)


def _said(deps: InvestigateDeps, note: Optional[str]) -> None:
    if text := clean_note(note):
        deps.event(text)


PERIODS = {"CY": "this year", "PY": "last year"}


def figure_line(fid: str, line: dict) -> str:
    """`F3: SOFP line "Bonds" under Non-current borrowings > Secured (SSM ifrs-full_Bonds) | this year, Company
    | value 1,200.00 | why the fill left it: ...`. The period is said as this year or last year, never as a year
    number: a blank template's dates are its own, not the company's. The section and the SSM name tell apart
    lines whose labels repeat."""
    value = line.get("value")
    when = f"{PERIODS.get(line.get('period'), line.get('period'))}, {line.get('entity_scope') or 'Company'}"
    amount = f" | value {value:,.2f}" if isinstance(value, (int, float)) else ""
    under = f" under {line['section']}" if line.get("section") else ""
    ssm = f" (SSM {line['ssm']})" if line.get("ssm") else ""
    return (f"{fid}: {line.get('statement') or ''} line \"{line.get('field') or line.get('name')}\"{under}{ssm} | "
            f"{when}{amount} | why the fill left it: {line.get('reason')}")


def _do(work):
    try:
        return work()
    except NotFound as exc:
        return str(exc)


# The toolkit --------------------------------------------------------------------------------------------

def identify_template(ctx: RunContext[InvestigateDeps], note: Optional[str] = None) -> str:
    """Which known template this is, or why it is not one.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    _said(ctx.deps, note)
    return identify_script.run(ctx.deps.book)


def list_rows(ctx: RunContext[InvestigateDeps], sheet: Optional[str] = None, start: int = 1, rows: int = 60,
              note: Optional[str] = None) -> str:
    """With no sheet, every sheet with its layout marks. With a sheet, its rows from `start`: each row's label,
    its SSM names and each value cell (empty, a number, a formula, locked). Header rows show which column is
    which year. `note`: one plain sentence for the person following the run."""
    _said(ctx.deps, note)
    return _do(lambda: list_script.run(ctx.deps.book, sheet, start, rows))


def find_rows(ctx: RunContext[InvestigateDeps], words: list[str], sheet: Optional[str] = None,
              note: Optional[str] = None) -> str:
    """Rows whose label or SSM name holds all the words, on every sheet or one. `note`: one plain sentence."""
    _said(ctx.deps, note)
    return _do(lambda: find_script.run(ctx.deps.book, words, sheet))


def read_cells(ctx: RunContext[InvestigateDeps], cells: list[str], note: Optional[str] = None) -> str:
    """What cells such as SOFP-CuNonCu!E30 hold, and whether the template locks them. `note`: one plain sentence."""
    _said(ctx.deps, note)
    return read_script.run(ctx.deps.book, cells)


class TrialWrite(BaseModel):
    figure: str = Field(description="The figure's id, such as F3; its value is written.")
    cell: str = Field(description="The cell, such as SOFP-CuNonCu!E30.")


def trial_fill(ctx: RunContext[InvestigateDeps], writes: list[TrialWrite], note: Optional[str] = None) -> str:
    """Write figures' values into a temporary copy of the template and say what read back. The template
    itself is never changed. `note`: one plain sentence."""
    _said(ctx.deps, note)
    deps, out, doc = ctx.deps, [], []
    for w in writes:
        line = deps.figures.get(w.figure.strip().upper())
        if line is None or not isinstance(line.get("value"), (int, float)):
            out.append(f"{w.figure}: there is no figure with that id and a value; show_figures lists them.")
        else:
            doc.append((w.cell, float(line["value"])))
    return "\n".join(out + ([trial_script.run(deps.book, doc)] if doc else []))


def compare_with_filled(ctx: RunContext[InvestigateDeps], sheet: Optional[str] = None,
                        note: Optional[str] = None) -> str:
    """The cells the fill changed in the template: what it wrote and where. `note`: one plain sentence."""
    _said(ctx.deps, note)
    if ctx.deps.filled is None:
        return "The filled file is not on the server, so there is nothing to compare."
    return _do(lambda: compare_script.run(ctx.deps.book, ctx.deps.filled, sheet))


# Proposals ----------------------------------------------------------------------------------------------

def show_figures(ctx: RunContext[InvestigateDeps]) -> str:
    """The figures that have no proposed place yet."""
    deps = ctx.deps
    left = [figure_line(fid, line) for fid, line in deps.figures.items() if fid not in deps.proposed]
    done = len(deps.figures) - len(left)
    return "\n".join(left + [f"{done} figure(s) already have a proposed place."]) if left else \
        f"Every one of the {done} figures has a proposed place."


def _column_words(book: Book, sheet: str, col: str) -> str:
    """What the column is, from the sheet's layout marks: `Company, this year`. Without them, nothing: a blank
    template's dates are placeholders, so a person reads the evidence instead of a misleading date."""
    layout = book.layout(sheet)
    for (entity, period), at in (layout.columns.items() if layout is not None else ()):
        if at == col:
            return f"{entity}, {PERIODS[period]}"
    return ""


def place_words(book: Book, sheet: str, row: int, col: str) -> str:
    """The cell in words: `SOFP-CuNonCu, row 49 "Trade and other receivables", column E (Company, this year)`."""
    label = row_label(book.sheet(sheet), row)[:80]
    column = _column_words(book, sheet, col)
    return (f"{sheet}, row {row}" + (f' "{label}"' if label else "") + f", column {col}"
            + (f" ({column})" if column else ""))


def _refusal(deps: InvestigateDeps, fid: str, cell: str) -> Optional[str]:
    """Why this cell cannot hold this figure, in one sentence; None when it can."""
    book = deps.book
    sheet, row, col = parse_ref(cell)
    sheet = book.sheet_name(sheet)
    ref = f"{sheet}!{col}{row}"
    kind, text = book.sheet(sheet).get(row, {}).get(col, ("", ""))
    if kind == "F":
        return f"{ref} holds a formula, so it is not an input cell."
    if book.locked(sheet, f"{col}{row}"):
        return f"{ref} is locked in the template, so nothing can be typed in it."
    if kind in ("N", "S") and (text or "").strip():
        return f"{ref} already holds {describe(book, sheet, row, col)}, so it is not free for this figure."
    if ref in deps.written:
        return f"The fill already wrote another figure in {ref}."
    taken = next((f for f, c in deps.proposed.items() if c == ref and f != fid), None)
    if taken:
        return f"{ref} is already proposed for {taken}; one cell holds one figure."
    return None


class Place(BaseModel):
    figure: str = Field(description="The figure's id, such as F3.")
    cell: str = Field(description="The cell, such as SOFP-CuNonCu!E30.")
    evidence: str = Field(description="One or two plain sentences: what on the sheet shows this cell holds this "
                                      "figure, such as the row's label and the column's year.")


def propose_places(ctx: RunContext[InvestigateDeps], places: list[Place], note: Optional[str] = None) -> str:
    """Propose a cell for each figure, with its evidence, for a person to check. A person decides; nothing is
    written to the workbook. Proposing a figure again replaces its earlier cell. `note`: one plain sentence."""
    deps = ctx.deps
    _said(deps, note)
    out = []
    for p in places:
        fid = p.figure.strip().upper()
        line = deps.figures.get(fid)
        if line is None:
            out.append(f"{p.figure}: there is no such figure; show_figures lists them.")
            continue
        if not p.evidence.strip():
            out.append(f"{fid}: not proposed. Say in evidence what on the sheet shows this cell holds it.")
            continue
        try:
            refusal = _refusal(deps, fid, p.cell)
            if refusal:
                out.append(f"{fid}: not proposed. {refusal}")
                continue
            sheet, row, col = parse_ref(p.cell)
            sheet = deps.book.sheet_name(sheet)
        except NotFound as exc:
            out.append(f"{fid}: not proposed. {exc}")
            continue
        with db.connect(immediate=True) as conn:
            store.propose(conn, deps.fill_id, line, sheet, f"{col}{row}", place_words(deps.book, sheet, row, col),
                          " ".join(p.evidence.split()))
        deps.proposed[fid] = f"{sheet}!{col}{row}"
        deps.writes += 1
        out.append(f"{fid}: proposed {sheet}!{col}{row}.")
    left = [f for f in deps.figures if f not in deps.proposed]
    return "\n".join(out + [f"{len(left)} figure(s) still without a place." if left else "Every figure has a place."])


class NotFoundFigure(BaseModel):
    figure: str = Field(description="The figure's id, such as F3.")
    why: str = Field(description="One plain sentence: why no single cell can be shown to hold it.")


class FinishInvestigation(BaseModel):
    summary: str = Field(description="Two or three plain sentences: what you found.")
    not_found: list[NotFoundFigure] = Field(default_factory=list,
                                            description="Each figure you found no place for, with why.")


def finish(ctx: RunContext[InvestigateDeps], report: FinishInvestigation) -> FinishInvestigation:
    """The run ends with every figure proposed or listed in not_found. The agent is sent back once with the
    figures it left out; after that, or at the last step, any finish is taken."""
    deps = ctx.deps
    named = {n.figure.strip().upper() for n in report.not_found}
    left = [f for f in deps.figures if f not in deps.proposed and f not in named]
    if left and not deps.refused_finish and ctx.run_step < deps.max_steps:
        deps.refused_finish = True
        raise ModelRetry(f"{', '.join(left)} have neither a proposed place nor a reason in not_found. Propose "
                         "a place for each, or list it in not_found with why.")
    deps.finish = report.model_dump()
    return report


TOOLS = (identify_template, list_rows, find_rows, read_cells, trial_fill, compare_with_filled, show_figures,
         propose_places)

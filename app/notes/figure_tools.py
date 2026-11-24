"""The notes agent's figure tools, on the two numeric notes: share capital
(`SC-` ids) and related parties (`RP-` ids).

Their numbers are figures, so they go through the figure store
(`app/figures/store.py`) like any other figure: every write has a history
row and the checks re-run, and its refusals come back word for word. A
figure on these sheets may carry a category, a share class or a
related-party relationship, named by the taxonomy member the first message
lists (`app/catalog/dimensions.py`).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app import db
from app.agents import pages
from app.catalog import lookup
from app.catalog.dimensions import CATEGORY_SHEETS, DimensionError, instance_key, numeric_category_catalog
from app.extraction.outline import HEADING
from app.extraction.tools import PrintedLine
from app.figures import store
from app.figures.sums import fmt_amount, money
from app.notes.state import NotesDeps
from app.notes.tools import actor
from app.runs.events import clean_note

NUMERIC = ("ISSUED_CAPITAL", "RELATED_PARTY")


def categories(standard: str, sheet: str) -> tuple[Optional[str], list[str]]:
    """(the axis, its members) for a numeric note sheet; (None, []) for a sheet without categories."""
    suffix = CATEGORY_SHEETS.get(sheet)
    if not suffix:
        return None, []
    catalog = numeric_category_catalog(standard)
    axis = next((a for a in catalog if a.endswith(suffix)), None)
    return axis, (catalog.get(axis, []) if axis else [])


def category_lines(standard: str) -> list[str]:
    """The categories each numeric sheet takes, for the first message."""
    out = []
    for sheet in CATEGORY_SHEETS:
        _axis, members = categories(standard, sheet)
        if members:
            out.append(f"- {sheet}: " + ", ".join(m.split("_", 1)[-1] for m in members))
    return out


class NoteFigure(BaseModel):
    field: str = Field(description="The field id, such as SC-12 or RP-9.")
    category: Optional[str] = Field(default=None, description="The share class or related-party category, by its "
                                                              "member name as listed; leave it out for the total.")
    lines: list[PrintedLine] = Field(description="The printed line or lines this figure comes from.")
    certainty: Literal["sure", "unsure"] = "sure"
    reason: str = Field(default="", description="One line: why this field and category, and any sum.")


def _field(deps: NotesDeps, fid: str):
    f = deps.outline.get(fid)
    if f is None or f.statement not in NUMERIC:
        return None, f"{fid} is not a share capital or related-party field id; read the outline in your first message."
    if f.kind == HEADING:
        return None, f"{f.id} is a heading, so save the figure in a field under it."
    return f, None


def _dimensions(deps: NotesDeps, f, category: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    if not category:
        return None, None
    axis, members = categories(deps.family.standard, f.sheet)
    if axis is None:
        return None, f"{f.id} takes no category; leave category out."
    wanted = category.strip().split("_", 1)[-1].lower()
    member = next((m for m in members if m.split("_", 1)[-1].lower() == wanted), None)
    if member is None:
        return None, (f"{category} is not a category of this sheet; use one of "
                      + ", ".join(m.split("_", 1)[-1] for m in members) + ".")
    return {axis: member}, None


def save_figures(ctx: RunContext[NotesDeps], figures: list[NoteFigure], note: Optional[str] = None) -> str:
    """Save share capital and related-party figures by field id and category, both years in one entry.
    Saving the same field and category again replaces it. Each figure is judged on its own.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    if not figures:
        return "Give at least one figure."
    report, planned = [], []
    with db.connect() as conn:
        for entry in figures:
            f, problem = _field(deps, entry.field)
            if problem is None and lookup.concept(conn, f.concept_uuid).text:
                problem = f"{f.id} is the note's text field, which holds words, not a figure."
            dims, bad = _dimensions(deps, f, entry.category) if f else (None, None)
            problem = problem or bad
            if problem is None and not entry.lines:
                problem = f"{f.id}: give the printed line or lines it comes from."
            if problem is None:
                problem = next((p for p in (pages.bad_pages(deps, [line.page], 1) for line in entry.lines) if p),
                               None)
            if problem:
                report.append(f"- {problem}")
                continue
            for period in ("CY", "PY"):
                amounts = [getattr(line, period.lower()) for line in entry.lines]
                if all(a is None for a in amounts):
                    continue
                lines = [store.Line(" ".join(line.label.split()), line.page, a, i, 1.0, f.statement)
                         for i, (line, a) in enumerate(zip(entry.lines, amounts)) if a is not None]
                planned.append((f, entry.category, period, store.FigureWrite(
                    f.concept_uuid, period, deps.entity, money(sum(a for a in amounts if a is not None)), lines,
                    dimensions=dims, certainty=entry.certainty, reason=deps.outline.readable(entry.reason))))
    saved = 0
    if planned:
        with db.connect(immediate=True) as conn:
            results = store.save_figures(conn, deps.run_id, [w for *_, w in planned], actor(deps))
        for (f, category, period, write), result in zip(planned, results):
            where = f"{f.id} {f.name}" + (f" ({category})" if category else "")
            if result["ok"]:
                saved += 1
                report.append(f"- {where}: {period} {fmt_amount(write.value)} saved.")
            else:
                report.append(f"- {where}: {period} not saved. {result['refused']}")
    if saved:
        deps.writes += 1
    deps.event("saved", clean_note(note) or f"Saved {saved} note figure(s).", {"saved": saved},
               [line.page for *_, w in planned for line in (w.lines or [])])
    return f"Saved {saved} of {len(planned)} figure(s) by year.\n" + "\n".join(report)


class NoteFigureClear(BaseModel):
    field: str
    category: Optional[str] = None
    period: Literal["CY", "PY", "both"] = "both"
    reason: str = ""


def clear_figures(ctx: RunContext[NotesDeps], figures: list[NoteFigureClear]) -> str:
    """Clear saved share capital or related-party figures. A cleared figure is blank again, never zero,
    and its history is kept."""
    deps = ctx.deps
    if not figures:
        return "Name at least one field."
    out, cleared = [], 0
    with db.connect(immediate=True) as conn:
        for entry in figures:
            f, problem = _field(deps, entry.field)
            dims, bad = _dimensions(deps, f, entry.category) if f else (None, None)
            if problem or bad:
                out.append(f"- {problem or bad}")
                continue
            try:
                key = instance_key(conn, f.concept_uuid, dims)
            except DimensionError as exc:
                out.append(f"- {f.id}: {exc}")
                continue
            for period in ("CY", "PY") if entry.period == "both" else (entry.period,):
                row = conn.execute("SELECT id FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ? "
                                   "AND entity_scope = ? AND dimension_key = ? AND value IS NOT NULL",
                                   (deps.run_id, f.concept_uuid, period, deps.entity, key)).fetchone()
                if row is None:
                    out.append(f"- {f.id}: nothing is saved for {period}.")
                    continue
                try:
                    store.clear_figure(conn, deps.run_id, row["id"], actor(deps), deps.outline.readable(entry.reason))
                    cleared += 1
                    out.append(f"- {f.id}: {period} cleared.")
                except store.Refused as exc:
                    out.append(f"- {f.id}: {period} not cleared. {exc}")
    if cleared:
        deps.writes += 1
        deps.event("cleared", f"Cleared {cleared} note figure(s).")
    return f"Cleared {cleared}.\n" + "\n".join(out)

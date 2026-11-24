"""The figures agent's tools for the template and the figures: find a field,
show a section, look up a definition, save and clear figures, add up.

Every tool takes a list, so one call does a batch (v1: one-at-a-time calls
used up the step limit). A bad request is answered with plain sentences as
the result, so it costs none of the tool's retries. Saves go through
`app/figures/store.save_figures` and nothing else: its refusals (the hard
stops) come back to the agent word for word.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app import db
from app.agents import pages
from app.runs.events import clean_note
from app.scope.fields import statement_words
from app.catalog import definitions
from app.extraction import feedback, outline_text
from app.extraction.grid import Column, Row
from app.extraction.outline import HEADING, TOTAL
from app.extraction.state import NAME, FiguresDeps
from app.figures import store
from app.figures.sums import fmt_amount, money
from app.starting import comparatives

AGENT = store.Actor("agent", NAME)


def _actor(deps: FiguresDeps) -> store.Actor:
    return store.Actor("agent", deps.actor_name)
MAX_QUERIES = 12
MAX_MATCHES = 6


def _saved(deps: FiguresDeps, entity: Optional[str] = None) -> dict[tuple[str, str], dict]:
    """The run's current figures for this entity (the run's own unless named), by (concept, period)."""
    with db.connect() as conn:
        return store.current_figures(conn, deps.run_id, entity or deps.entity)


def _new_points(deps: FiguresDeps, saved: dict, written: list[tuple[str, str]], entity: str = "") -> list[str]:
    """The advice after a save, each point once per field and entity until that field's value changes."""
    out = []
    for fid, point in feedback.advice(deps.outline, saved, written, deps.periods):
        uuid = deps.outline.fields[fid].concept_uuid
        now = tuple(((saved.get((uuid, p)) or {}).get("value"), (saved.get((uuid, p)) or {}).get("stated_value"))
                    for p in deps.periods)
        key = (fid, point) if not entity or entity == deps.entity else (fid, point, entity)
        if deps.advised.get(key) == now:
            continue
        deps.advised[key] = now
        out.append(point)
    return list(dict.fromkeys(out))


def _unknown(deps: FiguresDeps, fid: str) -> str:
    """Why an id cannot be used, in one plain sentence the agent can act on."""
    f = deps.outline.get(fid)
    if f is not None:
        return (f"{f.id} {f.name} is a field of the "
                f"{statement_words(f.statement, deps.family.variants.get(f.statement))}, "
                "which this run does not fill, so it cannot change it.")
    for found in deps.outline.grids.values():
        item = found.find(fid)
        example = found.example(item) if item is not None else None
        if isinstance(item, Row):
            return (f"{found.row_id(item.row)} is a row of the equity grid ({item.label}), not a cell; save by "
                    f"cell id, such as {example}.")
        if isinstance(item, Column):
            return (f"{found.column_id(item.letter)} is a column of the equity grid ({item.label}), not a cell; "
                    f"save by cell id, such as {example}.")
    return f"{fid} is not a field id in the outline; find the field with find_fields."


# Finding fields --------------------------------------------------------------

def _words(text: str) -> set[str]:
    """Words, with a plain plural made singular, so "banks" finds "bank"."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 1}


def _match(query: str, label: str, where: str, meaning: str) -> float:
    """Label first, then its place, then the official definition's words."""
    q, words = query.lower().strip(), _words(query)
    if not words:
        return 0.0
    exact = 1.0 if q == label.lower() else 0.0
    return (exact + SequenceMatcher(None, q, label.lower()).ratio() + len(words & _words(label)) / len(words)
            + 0.5 * len(words & _words(where)) / len(words) + 0.4 * len(words & _words(meaning)) / len(words))


def _candidates(deps: FiguresDeps) -> list[tuple[str, str, str, str, str]]:
    """(id, kind, name, where, meaning) for every field of the statements filled, and for an equity grid its
    rows and columns too; a grid cell is named with its column, so a row and a column together find it."""
    standard = deps.family.standard
    out = []
    for f in deps.outline.fields.values():
        if not deps.owns(f):
            continue
        meaning = definitions.definition_of(standard, f.primary_concept)
        if f.column_label:
            out.append((f.id, f.kind, f"{f.name}, {f.column_label}", f"{f.where} ({f.column_label})", meaning))
        else:
            out.append((f.id, f.kind, f.name, f.where, meaning))
    for statement in deps.statements:
        found = deps.outline.grids.get(statement)
        if found is None:
            continue
        out += [(found.row_id(r.row), f"{r.kind} row", r.label, " › ".join(r.path + (r.label,)), "")
                for r in found.rows if not r.heading]
        out += [(found.column_id(c.letter), f"{c.kind} column", c.label, c.label, "") for c in found.columns]
    return out


def find_fields(ctx: RunContext[FiguresDeps], queries: list[str]) -> str:
    """Find template fields by label or meaning (their official definitions count too), up to 12
    queries at a time. Each match gives the field id, whether it is a heading, a line or a total, and
    its place under its headings."""
    deps = ctx.deps
    if not queries:
        return "Give at least one query."
    if len(queries) > MAX_QUERIES:
        return f"Ask at most {MAX_QUERIES} queries at a time."
    candidates = _candidates(deps)
    parts = []
    for query in queries:
        scored = sorted(((s, c) for c in candidates if (s := _match(query, c[2], c[3], c[4])) > 0.6),
                        key=lambda pair: -pair[0])[:MAX_MATCHES]
        if not scored:
            parts.append(f"{query!r}: no field matches; try other words, or read the outline.")
            continue
        parts.append(f"{query!r}:\n" + "\n".join(f"- {c[0]} {c[1]}: {c[3]}" for _, c in scored))
    return "\n".join(parts)


def show_section(ctx: RunContext[FiguresDeps], fields: list[str]) -> str:
    """Show fields in detail, up to 6 at a time: each field's place, the parts of a total with
    their signs, everything nested under it, and what is saved there now. On the equity grid a row
    (such as CE-11) or a column (such as CE-C) shows each of its cells."""
    deps = ctx.deps
    if not fields:
        return "Name at least one field id."
    if len(fields) > 6:
        return "Ask for at most 6 fields at a time."
    values, periods = _shown_values(deps)
    out = []
    for fid in fields:
        f = deps.outline.get(fid)
        if f is not None:
            out.append(outline_text.section(deps.outline, f.id, values, periods))
            continue
        grids = [deps.outline.grids[s] for s in deps.statements if s in deps.outline.grids]
        shown = next((text for g in grids if (text := outline_text.grid_section(deps.outline, g, fid, values,
                                                                                periods))), None)
        out.append(shown or _unknown(deps, fid))
    return "\n\n".join(out)


def _shown_values(deps: FiguresDeps) -> tuple[dict, tuple[str, ...]]:
    """What show_section shows as saved: by period for one entity; on a Group run for the Reviewer, each
    entity's values labelled, such as "Group CY"."""
    entities = deps.shown_entities()
    values, periods = {}, []
    for entity in entities:
        label = (lambda p: f"{entity} {p}") if len(entities) > 1 else (lambda p: p)
        for (uuid, period), row in _saved(deps, entity).items():
            values[(uuid, label(period))] = (row["value"], row["stated_value"])
        periods += [label(p) for p in deps.periods]
    return values, tuple(periods)


def lookup_definitions(ctx: RunContext[FiguresDeps], queries: list[str]) -> str:
    """The official SSM definitions, up to 12 at a time. A query is a field id (that field's
    definition) or words (the best-matching definitions, with the fields that carry each)."""
    deps = ctx.deps
    if not queries:
        return "Give at least one field id or term."
    if len(queries) > MAX_QUERIES:
        return f"Ask at most {MAX_QUERIES} at a time."
    standard = deps.family.standard
    carriers: dict[str, list[str]] = {}
    for f in deps.outline.fields.values():
        if f.primary_concept and deps.owns(f) and f.kind != HEADING:
            carriers.setdefault(f.primary_concept, []).append(f.id)
    out = []
    for query in queries:
        f = deps.outline.get(query) or deps.outline.get(query.split(" ", 1)[0])   # "FP-s139 Trade ..." too
        if f is not None:
            text = definitions.definition_of(standard, f.primary_concept)
            out.append(f"{f.id} {f.name}: {text or 'no official definition is recorded for this field.'}")
            continue
        found = definitions.search(standard, query)
        if not found:
            out.append(f"{query!r}: no official definition matches.")
            continue
        lines = [f"- {e['label']}: {' '.join(e['definition'].split())}"
                 + (f" Fields: {', '.join(carriers[e['concept_id']])}." if e["concept_id"] in carriers
                    else " Not a field of this statement.") for e in found]
        out.append(f"{query!r}:\n" + "\n".join(lines))
    return "\n".join(out)


# Saving ------------------------------------------------------------------------

class PrintedLine(BaseModel):
    label: str = Field(description="The line's label as printed.")
    page: int = Field(description="The PDF page it is printed on.")
    cy: Optional[float] = Field(default=None, description="This year's amount, with the sign the field needs; "
                                                          "null when the line has no amount this year.")
    py: Optional[float] = Field(default=None, description="Last year's amount, with the sign the field needs; "
                                                          "null when the line has no amount last year.")


class FigureSave(BaseModel):
    field: str = Field(description="The field id from the outline, such as FP-s141.")
    lines: list[PrintedLine] = Field(description="The printed line or lines this figure comes from. "
                                                 "For each year the figure is the sum of their amounts.")
    total: Optional[Literal["printed", "no_breakdown"]] = Field(
        default=None, description="Only on a total: printed records the amount the report prints beside the "
                                  "template's own sum; no_breakdown keeps it as the figure when the report "
                                  "gives no parts.")
    certainty: Literal["sure", "unsure"] = "sure"
    reason: str = Field(default="", description="One line: why this field, and the arithmetic of any sum.")


def _writes(deps: FiguresDeps, entry: FigureSave, concept_uuid: str, section: str,
            entity: str) -> list[tuple[str, store.FigureWrite]]:
    out = []
    for period in ("CY", "PY"):   # a prior year on first statements is the store's to refuse
        amounts = [getattr(line, period.lower()) for line in entry.lines]
        if all(a is None for a in amounts):
            continue
        lines = [store.Line(" ".join(line.label.split()), line.page, a, i, 1.0, section)
                 for i, (line, a) in enumerate(zip(entry.lines, amounts)) if a is not None]
        value = money(sum(a for a in amounts if a is not None))
        out.append((period, store.FigureWrite(concept_uuid, period, entity, value, lines,
                                              certainty=entry.certainty, reason=deps.outline.readable(entry.reason),
                                              total=entry.total)))
    return out


def save_figures(ctx: RunContext[FiguresDeps], figures: list[FigureSave], note: Optional[str] = None) -> str:
    """Save figures by field id, both years in one entry. Saving a field again replaces it.
    Each figure is judged on its own: a refused one does not stop the others.
    `note`: one plain sentence for the person following the run: what you are doing and why.
    """
    return save_for(ctx.deps, figures, note)


def save_for(deps: FiguresDeps, figures: list[FigureSave], note: Optional[str] = None,
             entity: Optional[str] = None) -> str:
    """save_figures for one entity's columns: the run's own unless named (the Reviewer names the entity of the
    comments it answers)."""
    entity = entity or deps.entity
    if not figures:
        return "Give at least one figure."
    report: list[str] = []
    planned: list[tuple[str, str, store.FigureWrite]] = []
    for entry in figures:
        f = deps.outline.get(entry.field)
        if not deps.owns(f):
            report.append(f"- {_unknown(deps, entry.field)}")
            continue
        if not entry.lines:
            report.append(f"- {f.id} {f.name}: not saved. Give the printed line or lines it comes from.")
            continue
        bad_page = next((p for p in (pages.bad_pages(deps, [line.page], 1) for line in entry.lines) if p), None)
        if bad_page:
            report.append(f"- {f.id} {f.name}: not saved. {bad_page}")
            continue
        writes = _writes(deps, entry, f.concept_uuid, " › ".join(f.path), entity)
        if not writes:
            report.append(f"- {f.id} {f.name}: not saved. No line has an amount for either year.")
        planned += [(f.id, period, w) for period, w in writes]
    saved_now: list[tuple[str, str]] = []
    kept: list[tuple[str, str, store.FigureWrite]] = []
    if planned:
        current = _saved(deps, entity)
        kept = [p for p in planned if p[1] == "PY" and comparatives.is_kept(current.get((p[2].concept_uuid, "PY")))]
        planned = [p for p in planned if p not in kept]
        with db.connect(immediate=True) as conn:
            results = store.save_figures(conn, deps.run_id, [w for _, _, w in planned], _actor(deps)) if planned \
                else []
            compared = [comparatives.compare(conn, deps.run_id, current[(w.concept_uuid, "PY")], w.value, w.lines,
                                             by=deps.actor_name, reason=w.reason, sign_note=_sign_note(deps, fid))
                        for fid, _, w in kept]
            if kept:   # after the readings are recorded: the comparatives check reads them
                store.recalculate(conn, deps.run_id)
        by_field: dict[str, list[str]] = {}
        for (fid, _period, _write), answer in zip(kept, compared):
            by_field.setdefault(fid, []).append(f"PY not saved: last year's figure is kept from the starting "
                                                f"workbook. {answer}")
        for (fid, period, write), result in zip(planned, results):
            if result["ok"]:
                saved_now.append((fid, period))
                printed = " as printed" if write.total == "printed" else ""
                by_field.setdefault(fid, []).append(f"{period} {fmt_amount(write.value)} saved{printed}")
            else:
                by_field.setdefault(fid, []).append(f"{period} not saved. {result['refused']}")
        for fid, parts in by_field.items():
            text = "; ".join(parts)
            report.append(f"- {fid} {deps.outline.fields[fid].name}: {text}{'' if text.endswith('.') else '.'}")
    compared_now = len(kept)
    if saved_now or compared_now:   # a recorded comparison is work too: the checks and coverage follow it
        deps.writes += 1
    refused = len(planned) - len(saved_now)
    head = _head(len(saved_now), len(planned), refused, compared_now)
    points = _new_points(deps, _saved(deps, entity), saved_now, entity) if saved_now else []
    said = (f"Saved {len(saved_now)} figure(s){f', {refused} refused' if refused else ''}." if planned or not kept
            else head)
    deps.event("saved", clean_note(note) or said,
               {"saved": [f"{fid} {p}" for fid, p in saved_now], "points": len(points)},
               [line.page for _, _, w in planned for line in (w.lines or [])])
    out = [head] + report
    if points:
        out += ["Points to check (advice, not refusals):"] + [f"- {p}" for p in points]
    return "\n".join(out)


def _head(saved: int, planned: int, refused: int, compared: int) -> str:
    """The save's first line: what was saved and what was compared with last year's workbook."""
    parts = []
    if planned:
        parts.append(f"Saved {saved} of {planned} figure(s) by year" + (f"; {refused} refused" if refused else ""))
    if compared:
        parts.append(f"compared {compared} of last year's figures kept from the workbook with the report")
    if not parts:
        return "Nothing was saved."
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "."


def _sign_note(deps: FiguresDeps, fid: str) -> str:
    """The row's overall sign in words, for a sign-only difference with last year's workbook."""
    sign, top = deps.outline.overall_sign(fid)
    if top is None:
        return ""
    return (f"{deps.outline.fields[top].name} {'subtracts' if sign < 0 else 'adds'} this field overall, so a "
            f"positive figure here {'reduces' if sign < 0 else 'increases'} it.")


class FigureClear(BaseModel):
    field: str = Field(description="The field id.")
    period: Literal["CY", "PY", "both"] = "both"
    reason: str = Field(default="", description="One line: why it is cleared.")


def clear_figures(ctx: RunContext[FiguresDeps], figures: list[FigureClear], note: Optional[str] = None) -> str:
    """Clear saved figures, for example a coarse figure replaced by its parts. A cleared figure is
    blank again, never zero, and its history is kept.
    `note`: one plain sentence for the person following the run: what you are doing and why.
    """
    return clear_for(ctx.deps, figures, note)


def clear_for(deps: FiguresDeps, figures: list[FigureClear], note: Optional[str] = None,
              entity: Optional[str] = None) -> str:
    """clear_figures for one entity's columns: the run's own unless named."""
    if not figures:
        return "Name at least one field."
    saved = _saved(deps, entity)
    out, cleared = [], 0
    with db.connect(immediate=True) as conn:
        for entry in figures:
            f = deps.outline.get(entry.field)
            if not deps.owns(f):
                out.append(f"- {_unknown(deps, entry.field)}")
                continue
            for period in ("CY", "PY") if entry.period == "both" else (entry.period,):
                row = saved.get((f.concept_uuid, period))
                if row is None or (row["value"] is None and row["stated_value"] is None):
                    out.append(f"- {f.id} {f.name}: nothing is saved for {period}.")
                    continue
                if f.kind == TOTAL and row["children_status"] != "aggregate_only" and row["stated_value"] is None:
                    out.append(f"- {f.id} {f.name}: {period} is added up from its parts, so clear those instead.")
                    continue
                try:
                    store.clear_figure(conn, deps.run_id, row["id"], _actor(deps), deps.outline.readable(entry.reason))
                    cleared += 1
                    out.append(f"- {f.id} {f.name}: {period} cleared.")
                except store.Refused as exc:
                    out.append(f"- {f.id} {f.name}: {period} not cleared. {exc}")
    if cleared:
        deps.writes += 1
        deps.event("cleared", clean_note(note) or f"Cleared {cleared} figure(s).")
    return f"Cleared {cleared}.\n" + "\n".join(out)


# Adding up ---------------------------------------------------------------------

class Sum(BaseModel):
    name: str = Field(description="What this sum is, for example 'note 6 trade receivables, CY'.")
    amounts: list[float] = Field(description="The amounts to add, each with its sign.")


def add_up(ctx: RunContext[FiguresDeps], sums: list[Sum]) -> str:
    """Add up lists of amounts exactly, several sums at a time."""
    if not sums:
        return "Give at least one sum."
    return "\n".join(f"{s.name}: {fmt_amount(money(sum(s.amounts)))} ({len(s.amounts)} amounts)" for s in sums)

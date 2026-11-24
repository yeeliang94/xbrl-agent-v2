"""Coverage and the finish: every note is placed, routed to another template
where it is really placed, or reported with a reason (v1 lessons: notes
were silently lost; a jump in the numbering can be a missed note).

Code works coverage out from the store across every session, by source
blocks: a placed note is open while any block of it, up to its last placed
block, is in no field, or a part of a split note is missing. A report
excuses a note left wholly unplaced, never words left out of a placed one.
The agent's reports go into `note_reports` through
`app/notes/store_reports.py`.

The finish (as the figures agent's, `app/extraction/checking.py`): the agent
is sent back once, with every reason at once: in the placing session while
coverage is open, in a formatting session while a note of its group that
holds a table or a look it set is not previewed since, in the numeric
session while nothing is saved or reported. After that one refusal it may
finish by listing each open point with its reason, unless coverage changed
in a way it was not told. At the last step any finish is taken.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from app import db
from app.notes import source, store, store_reports
from app.notes.state import NotesDeps

MAX_PREVIEWS = 3
MAX_REPORTS = 12


def find_listed(notes_list: list[dict], wanted: str) -> Optional[int]:
    """The position in the notes list of a note named by its number, or by its title."""
    number = source.plain_number(wanted)
    for i, n in enumerate(notes_list):
        if number and source.plain_number(n["number"]) == number:
            return i
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", (wanted or "").lower()).split())
    for i, n in enumerate(notes_list):
        if words and " ".join(re.sub(r"[^a-z0-9]+", " ", n["title"].lower()).split()) == words:
            return i
    return None


def _holes(notes_list: list[dict]) -> list[str]:
    """Whole note numbers the list skips between two numbers it has."""
    numbers = sorted({int(n["number"].rstrip(".")) for n in notes_list if n["number"].rstrip(".").isdigit()})
    return [str(x) for a, b in zip(numbers, numbers[1:]) for x in range(a + 1, b)]


@dataclass
class Status:
    lines: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    open: list[str] = field(default_factory=list)
    by_note: dict[int, str] = field(default_factory=dict)   # listed position -> its open point
    placed: int = 0
    reported: int = 0


def _parts(here: list[dict]) -> tuple[str, list[int]]:
    """Which parts of a split note are placed, in words, and the part numbers still missing."""
    parts = max(n["parts"] for n in here)
    if parts <= 1:
        return "placed", []
    got = sorted({n["part"] for n in here})
    return (f"part{'s' if len(got) > 1 else ''} {', '.join(map(str, got))} of {parts} placed",
            [k for k in range(1, parts + 1) if k not in got])


def status(conn, deps: NotesDeps) -> Status:
    """Coverage by source blocks: a note counts as placed when every block of it, up to its last placed block,
    is in a field (its own or another note's), and every part of a split note is placed."""
    notes = store.run_notes(conn, deps.run_id, blocks=True)
    reports = store_reports.run_reports(conn, deps.run_id)
    reported_numbers = {source.plain_number(r["note_number"]) for r in reports if r["note_number"]}
    held = {b["id"] for n in notes if n["field"] for b in n["blocks"]}
    out = Status(reported=len(reports))
    matched: set[int] = set()
    for i, listed in enumerate(deps.notes_list):
        number = source.plain_number(listed["number"])
        here = [n for n in notes if n["field"] and (source.plain_number(n["number"]) == number if number
                                                    else n["title"].lower() == listed["title"].lower())]
        matched.update(n["id"] for n in here)
        pages = f"p{listed['first_page']}" + (f"-{listed['last_page']}" if listed["last_page"] != listed["first_page"]
                                              else "")
        label = listed['number'] or listed['title']
        name = f"{listed['number'] or '(no number)'} {listed['title']}: {pages}"
        if here:
            out.placed += 1
            where = "; ".join(f"note id {n['id']} in {deps.outline.note_ids.get(n['field']['node_uuid'], '?')} "
                              f"{n['field']['label']}" + (f" (part {n['part']} of {n['parts']})" if n["parts"] > 1
                                                          else "") for n in here)
            span = source.note_span(deps.contents, deps.notes_list, i, deps.page_count)
            judged, missing = source.unplaced(span, {b["id"] for n in here for b in n["blocks"]}, held, listed)
            placed_words, missing_parts = _parts(here)
            gaps = []
            if missing:
                gaps.append(f"{len(missing)} of {len(judged)} blocks are in no field ({source.ranges(missing, span)})")
            if missing_parts:
                gaps.append(f"part {', '.join(map(str, missing_parts))} is not placed")
            out.lines.append(f"{name} — placed: {where}" + (f"; {'; '.join(gaps)}" if gaps else ""))
            if gaps:   # a report never excuses words left out of a placed note
                point = f"Note {label}: {placed_words}; {'; '.join(gaps)}."
                out.open.append(point)
                out.by_note[i] = point
        elif number and number in reported_numbers:
            kinds = sorted({r["kind"].replace("_", " ") for r in reports
                            if source.plain_number(r["note_number"]) == number})
            out.lines.append(f"{name} — reported ({', '.join(kinds)})")
        else:
            out.lines.append(f"{name} — not placed or reported yet")
            point = f"Note {label} is neither placed nor reported."
            out.open.append(point)
            out.by_note[i] = point
    for hole in _holes(deps.notes_list):
        if hole not in reported_numbers and not any(source.plain_number(n["number"]) == hole for n in notes):
            out.open.append(f"The list has no note {hole}: check the pages for a missed note, or report it as a "
                            "gap if the numbering really skips it.")
    out.extra = [f"note id {n['id']} (note {n['number'] or '-'} {n['title']}) in {n['field']['label']}"
                 for n in notes if n["field"] and n["id"] not in matched]
    out.reports = [f"{r['kind'].replace('_', ' ')}" + (f", note {r['note_number']}" if r["note_number"] else "")
                   + f": {r['reason']}" for r in reports]
    return out


# Reports ---------------------------------------------------------------------

class Gap(BaseModel):
    note: str = Field(default="", description="The note's number as printed, if the gap is in one note.")
    pages: list[int] = Field(description="The PDF pages concerned.")
    reason: str = Field(description="One plain sentence: what is missing or wrong in the captured text.")
    after_block: Optional[str] = Field(default=None, description="The block id after which the missing text "
                                                                 "belongs, such as p24b2, when you can tell.")


def _report(deps: NotesDeps, kind: str, note: str, node_uuid, pages: list[int], reason: str,
            after_block: Optional[str] = None) -> str:
    bad = [p for p in pages if not 1 <= p <= deps.page_count]
    if bad:
        return f"Page {bad[0]} is outside the document, which has {deps.page_count} pages."
    try:
        with db.connect(immediate=True) as conn:
            store_reports.add_report(conn, deps.run_id, kind, note_number=note, node_uuid=node_uuid, pages=pages,
                                     reason=deps.outline.readable(reason), actor_name=deps.actor_name,
                                     after_block=after_block)
    except store_reports.ReportRefused as exc:
        return str(exc)
    deps.writes += 1
    return "reported."


def report_gap(ctx: RunContext[NotesDeps], gaps: list[Gap]) -> str:
    """Report a capture problem: text missing from the transcription, or contradicting the page, or a
    numbering gap that is really in the report. Report it and carry on; a best-effort note is still placed."""
    if not gaps:
        return "Give at least one gap."
    if len(gaps) > MAX_REPORTS:
        return f"Report at most {MAX_REPORTS} at a time."
    return "\n".join(f"- {g.note or 'gap'}: {_report(ctx.deps, 'source_gap', g.note, None, g.pages, g.reason, g.after_block)}"
                     for g in gaps)


class MissingField(BaseModel):
    field: str = Field(description="The required note field id.")
    reason: str = Field(description="One plain sentence: why the report gives nothing for it.")


def report_missing_field(ctx: RunContext[NotesDeps], fields: list[MissingField]) -> str:
    """Report a required note field that the report does not support, so a person can decide."""
    deps = ctx.deps
    if not fields:
        return "Name at least one field."
    out = []
    for m in fields:
        f = deps.outline.note_field(m.field)
        if f is None:
            out.append(f"- {m.field} is not a note field id; find the field with find_note_fields.")
        elif not f.mandatory:
            out.append(f"- {m.field} is not a required field, so leaving it empty needs no report.")
        else:
            out.append(f"- {m.field}: {_report(deps, 'missing_mandatory_field', '', f.field_id, [], m.reason)}")
    return "\n".join(out)


class Routed(BaseModel):
    note: str = Field(description="The note's number as printed.")
    template: str = Field(description="Where it is really placed, such as the related parties template.")
    reason: str = Field(description="One plain sentence.")


def report_coverage(ctx: RunContext[NotesDeps], routed: Optional[list[Routed]] = None) -> str:
    """Check that every note in the notes list is placed or reported, and the numbering for holes. Give any
    note placed in another template (for example a note whose numbers go only in the related parties
    template) in routed. Report again after later changes; the last report counts."""
    deps = ctx.deps
    out = []
    for r in routed or []:
        position = find_listed(deps.notes_list, r.note)
        pages = ([deps.notes_list[position]["first_page"]] if position is not None else [])
        said = _report(deps, "routed_elsewhere", r.note, None, pages, f"Placed in {r.template}: {r.reason}")
        out.append(f"- Note {r.note} routed to {r.template}: {said}")
    with db.connect() as conn:
        found = status(conn, deps)
    deps.coverage_open, deps.coverage_at = found.open, deps.writes
    deps.event("coverage", f"Coverage: {found.placed} note(s) placed, {found.reported} report(s), "
                           f"{len(found.open)} still open.",
               {"placed": found.placed, "reports": found.reported, "open": len(found.open)})
    head = ("Every note in the list is placed or reported." if not found.open
            else f"{len(found.open)} point(s) are open:")
    return "\n".join(out + [head, *[f"- {x}" for x in found.open]])


# The finish ------------------------------------------------------------------

class FinishReport(BaseModel):
    summary: str = Field(description="A few sentences: what you placed and how you checked it.")
    unresolved: list[str] = Field(default_factory=list,
                                  description="Each point left open, one sentence each with its reason.")


def _has_table(note: dict) -> bool:
    return any(b["kind"] == "table" for b in note.get("blocks", []))


def unpreviewed(conn, deps: NotesDeps) -> list[dict]:
    """The notes a formatting session still owes a preview: in its group, holding a table or with a look it
    set, changed since their last preview and not flagged for a person. Plain prose with no look set needs
    none."""
    out = []
    for n in store.run_notes(conn, deps.run_id, blocks=True):
        mine = n["id"] in deps.group if deps.group else n["id"] in deps.touched
        if mine and n["field"] and (_has_table(n) or n["id"] in deps.looked) \
                and n["format_state"] != "check_formatting" and deps.previewed_at.get(n["id"]) != n["revision"]:
            out.append(n)
    return out


def _coverage_reasons(conn, deps: NotesDeps) -> tuple[list[str], bool]:
    """The placing session's coverage reasons, and whether they hold points the agent has not been told."""
    now_open = status(conn, deps).open
    if deps.coverage_open is None:
        return ["Account for every note with report_coverage."], False
    if now_open != deps.coverage_open and now_open != deps.coverage_told:
        deps.coverage_told = now_open
        return [f"Coverage changed since your last report_coverage: {len(now_open)} point(s) are open now"
                + (": " + " ".join(now_open) if now_open else ".") + " Report coverage again."], True
    if now_open:
        return [f"Coverage leaves {len(now_open)} point(s) open: " + " ".join(now_open)], False
    return [], False


def _reasons(deps: NotesDeps) -> tuple[list[str], bool]:
    """Why the session may not finish yet, and whether any reason is news to the agent."""
    out, news = [], False
    with db.connect() as conn:
        anything = conn.execute("SELECT (SELECT COUNT(*) FROM notes WHERE run_id = ?) + "
                                "(SELECT COUNT(*) FROM note_reports WHERE run_id = ?)",
                                (deps.run_id, deps.run_id)).fetchone()[0]
        figures = conn.execute("SELECT COUNT(*) FROM figure_history WHERE run_id = ? AND actor_name = ?",
                               (deps.run_id, deps.actor_name)).fetchone()[0]
        if deps.session == "placing":
            if not anything:
                out.append("Nothing is placed or reported yet: place the notes with place_note.")
            found, news = _coverage_reasons(conn, deps)
            out += found
        if deps.session == "look":
            waiting = unpreviewed(conn, deps)
            if waiting:
                names = ", ".join(f"note id {n['id']} (note {n['number'] or n['title']})" for n in waiting)
                out.append(f"Preview these notes, several fields in one call if you like, or flag what still "
                           f"differs with flag_formatting: {names}.")
    if deps.session == "numeric" and not figures and deps.writes == 0:
        out.append("Save the share capital and related-party figures with save_figures, or report what the "
                   "report does not show with report_gap.")
    return out, news


def finish(ctx: RunContext[NotesDeps], report: FinishReport) -> FinishReport:
    """A session ends with its work previewed and accounted for, or honestly left open. The agent is sent back
    once with every reason; after that it may finish by listing what is open, unless a reason is news to it."""
    deps = ctx.deps
    reasons, news = _reasons(deps)
    last_step = ctx.run_step >= deps.max_steps
    honest = bool(report.unresolved) and deps.refused_finish and not news
    if reasons and not honest and not last_step:
        deps.refused_finish = True
        deps.event("notice", "The finish was sent back: " + reasons[0])
        raise ModelRetry("Not finished yet:\n" + "\n".join(f"- {r}" for r in reasons) + "\nFix these. If one "
                         "cannot be fixed because of what the report shows, finish again and list each open point "
                         "in unresolved with its reason.")
    deps.finish = {**report.model_dump(), "open_when_finished": reasons, "at_last_step": last_step and bool(reasons)}
    return report

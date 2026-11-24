"""The Reviewer's note tools: show a note, move it, set its look, preview its
field and redo it from its pages, each write naming the comments it answers.

Writes go through the note store (`app/notes/store.py`), so its hard stops
and history rows are the same as for the notes agent; each is tagged with the
round and its comments, and its result ends with the server's own count of
what the round changed so far, notes included. The look vocabulary and the
preview are the notes agent's (`app/notes/look_tools.py`). No tool takes a
note's words: a wrong word is a redo from the pages.

v1's lesson "never clear a note's last placement"
(`notes/reviewer_agent.py` 449-460) is feedback here, not a stop: taking a
note out of its only field is done, and the result says plainly that the
note is now placed nowhere.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app import db
from app.notes import look_tools, source, store
from app.notes import tools as notes_tools
from app.review import note_parts
from app.review.state import ReviewDeps
from app.review.tools import _bad_ids, _report_text
from app.runs.events import clean_note

MAX_SHOW = 4
_TEXT = 300


def _actor(deps: ReviewDeps) -> store.Actor:
    return store.Actor("agent", deps.actor_name)


def _reason(deps: ReviewDeps, note: Optional[str]) -> str:
    """The history row's reason: the agent's note, with field ids named as a person reads them."""
    return deps.outline.readable(clean_note(note) or "")


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= _TEXT else text[:_TEXT - 1] + "…"


def _marks(look: dict, keys=("bold", "italic", "underline")) -> list[str]:
    out = [k for k in keys if look.get(k)]
    if look.get("align"):
        out.append(f"align {look['align']}")
    if look.get("indent"):
        out.append(f"indent {look['indent']}")
    if look.get("valign"):
        out.append(f"valign {look['valign']}")
    if look.get("unsure"):
        out.append(f"not sure: {', '.join(look['unsure'])}")
    return out


def _row_look(row: dict) -> list[str]:
    out = [row["role"]]
    out += [k for k in ("bold", "shaded") if row.get(k)]
    if row.get("indent"):
        out.append(f"indent {row['indent']}")
    line = row.get("line_below")
    if line:
        cols = ", ".join(str(c + 1) for c in line["columns"]) if line["columns"] else "every column"
        out.append(f"{line['style']} line below across {cols}")
    if row.get("unsure"):
        out.append(f"not sure: {', '.join(row['unsure'])}")
    return out


def describe_block(b: dict) -> list[str]:
    """A stored block with its look, rows and columns numbered from 1 as set_note_look takes them."""
    marks = lambda look: f" [{', '.join(_marks(look))}]" if _marks(look) else ""  # noqa: E731
    if b["kind"] in ("heading", "paragraph"):
        level = f" level {b['level']}" if b["kind"] == "heading" else ""
        return [f"{b['id']} {b['kind']}{level}{marks(b['look'])}: {_short(b['text'])}"]
    if b["kind"] == "list":
        return [f"{b['id']} list{marks(b['look'])}:"] + [f"    - {_short(i['text'])}" for i in b["items"]]
    columns = "; ".join(f"{n} {c['role']}" + (f" {c['width']}%" if c.get("width") else "")
                        + (f" align {c['align']}" if c.get("align") else "") for n, c in enumerate(b["columns"], 1))
    out = [f"{b['id']} table, frame {b['frame']}" + (f", font {b['font_pt']} pt" if b.get("font_pt") else "")
           + f", columns: {columns}:"]
    for n, row in enumerate(b["rows"], 1):
        cells = " | ".join((_short(c["text"]) or "·") + (f" [{', '.join(_marks(c['look']))}]" if _marks(c["look"])
                                                         else "") for c in row["cells"])
        out.append(f"    row {n} ({', '.join(_row_look(row))}): {cells}")
    return out


def _where(deps: ReviewDeps, n: dict) -> str:
    if not n["field"]:
        return "not placed in any field"
    fid = deps.outline.note_ids.get(n["field"]["node_uuid"], "")
    return f"in {fid + ' ' if fid else ''}{n['field']['label']} (position {n['position']})"


def note_heading(deps: ReviewDeps, n: dict) -> str:
    split = f", part {n['part']} of {n['parts']}" if n["parts"] > 1 else ""
    state = n["format_state"].replace("_", " ")
    return (f"Note id {n['id']}: note {n['number'] or '(no number)'} {n['title']}{split}, pages "
            f"{', '.join(map(str, n['pages']))}, {_where(deps, n)}, formatting {state}"
            + (f" ({n['format_reason']})" if n["format_reason"] else "") + ".")


def show_notes(ctx: RunContext[ReviewDeps], note_ids: list[int]) -> str:
    """Show saved notes as they are now, up to 4 at a time: where each is placed, its blocks with their ids
    and look, and each table's columns and rows numbered from 1, as set_note_look takes them."""
    deps = ctx.deps
    if not note_ids:
        return "Name at least one note id."
    if len(note_ids) > MAX_SHOW:
        return f"Ask for at most {MAX_SHOW} notes at a time."
    out = []
    with db.connect() as conn:
        for note_id in dict.fromkeys(note_ids):
            try:
                n = store.get_note(conn, deps.run_id, note_id)
            except store.Refused:
                out.append(f"There is no note id {note_id} in this run.")
                continue
            lines = [note_heading(deps, n)]
            for b in n["blocks"]:
                lines += describe_block(b)
            out.append("\n".join(lines))
    return "\n\n".join(out)


def find_note_fields(ctx: RunContext[ReviewDeps], queries: list[str]) -> str:
    """Find note fields by label or meaning, up to 12 queries at a time: each match gives the field id, its
    template, its place under its headings, and whether it is required or the template's catch-all."""
    return notes_tools.find_note_fields(ctx, queries)


class NoteMove(BaseModel):
    note_id: int
    to_field: Optional[str] = Field(description="The note field id it belongs in, such as LIST-40; null takes it "
                                                "out of its field.")
    comment_ids: list[int] = Field(default_factory=list, description="The comments this move answers.")


def _placed_elsewhere(conn, run_id: int, n: dict) -> bool:
    for r in conn.execute("SELECT id, note_number, title FROM notes WHERE run_id = ? AND node_uuid IS NOT NULL "
                          "AND id != ?", (run_id, n["id"])):
        same = (source.plain_number(r["note_number"]) == source.plain_number(n["number"]) if n["number"]
                else r["title"].lower() == n["title"].lower())
        if same:
            return True
    return False


def move_notes(ctx: RunContext[ReviewDeps], moves: list[NoteMove], note: Optional[str] = None) -> str:
    """Move saved notes to another note field, last there, or take a note out of its field, naming the
    comments each move answers. A note keeps its blocks and look. The result ends with what the round has
    changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why."""
    deps = ctx.deps
    if not moves:
        return "Give at least one move."
    out, moved = [], 0
    for m in moves:
        problem = _bad_ids(deps, m.comment_ids)
        target = deps.outline.note_field(m.to_field) if m.to_field else None
        if problem is None and m.to_field and target is None:
            problem = notes_tools.unknown_field(m.to_field)
        if problem:
            out.append(f"- Note id {m.note_id}: {problem}")
            continue
        try:
            with db.connect(immediate=True) as conn, store.tagged(deps.round_id, m.comment_ids):
                n = store.get_note(conn, deps.run_id, m.note_id)
                if target is None:
                    if n["field"] is None:
                        out.append(f"- Note id {m.note_id}: already in no field; nothing changed.")
                        continue
                    last = n["field"] is not None and not _placed_elsewhere(conn, deps.run_id, n)
                    store.clear_note(conn, deps.run_id, m.note_id, _actor(deps), reason=_reason(deps, note))
                    said = f"- Note id {m.note_id}: taken out of its field."
                    if last:
                        said += (" It is now placed nowhere, so mTool will not get it and a person sees it as not "
                                 "placed. If the comment asked for another field, move it there instead.")
                elif n["field"] and n["field"]["node_uuid"] == target.field_id:
                    out.append(f"- Note id {m.note_id}: already in {m.to_field} {target.label}; nothing changed.")
                    continue
                else:
                    store.move_note(conn, deps.run_id, m.note_id, target.field_id, _actor(deps),
                                    reason=_reason(deps, note))
                    said = f"- Note id {m.note_id}: moved to {m.to_field} {target.label}."
        except store.Refused as exc:
            out.append(f"- Note id {m.note_id}: not moved. {exc}")
            continue
        moved += 1
        out.append(said)
    if moved:
        deps.writes += 1
        deps.event("moved", clean_note(note) or f"Moved {moved} note(s).", {"note_moves": moved})
    return "\n".join([f"Moved {moved} of {len(moves)}."] + out + ["", _report_text(deps)])


class ReviewLook(look_tools.LookChange):
    comment_ids: list[int] = Field(default_factory=list, description="The comments this change answers.")


def set_note_look(ctx: RunContext[ReviewDeps], changes: list[ReviewLook], note: Optional[str] = None) -> str:
    """Set the look of saved notes, naming the comments each change answers: look values only, never words.
    A heading, paragraph or list takes bold, italic, underline, align and indent; a table takes frame and
    font_pt; a row takes role, indent, bold, shaded and line_below; a column takes role, width and align; a cell
    takes bold, italic, underline, align and valign. Rows and columns are numbered from 1, as show_notes gives
    them. The changes to one note for the same comments are saved together; one that cannot apply leaves them
    unsaved. The result ends with what the round has changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why."""
    deps = ctx.deps
    if not changes:
        return "Give at least one change."
    groups: dict[tuple, list[ReviewLook]] = {}
    for c in changes:
        groups.setdefault((c.note_id, tuple(sorted(set(c.comment_ids)))), []).append(c)
    out, done = [], 0
    for (note_id, ids), group in groups.items():
        problem = _bad_ids(deps, list(ids))
        if problem:
            out.append(f"- Note id {note_id}: {problem}")
            continue
        try:
            with db.connect(immediate=True) as conn, store.tagged(deps.round_id, ids):
                problem = look_tools.apply_looks(conn, deps.run_id, note_id, group, _actor(deps), _reason(deps, note))
            if problem:
                out.append(f"- Note id {note_id}: not changed. {problem}")
                continue
        except store.Refused as exc:
            out.append(f"- Note id {note_id}: not changed. {exc}")
            continue
        done += 1
        out.append(f"- Note id {note_id}: look changed ({len(group)} change(s)). Preview it to check.")
    if done:
        deps.writes += 1
        deps.event("look", clean_note(note) or f"Changed the look of {done} note(s).", {"notes": done})
    return "\n".join(out + ["", _report_text(deps)])


async def preview_notes(ctx: RunContext[ReviewDeps], note_ids: list[int], note: Optional[str] = None) -> Any:
    """Draw each note's field as mTool gets it, on mTool's page (A4, 20 mm margins), with every note placed in
    that field: the pictures, the characters used against mTool's limit, the size tier, and whether a table is
    too wide. Three previews a note in this round; the result says how many are left. Compare the pictures with
    the source page.
    `note`: one plain sentence for the person following the round: what you are doing and why."""
    return await look_tools.preview_note(ctx, note_ids, note)


class Redo(BaseModel):
    note_id: int
    comment_ids: list[int] = Field(default_factory=list, description="The comments this redo answers.")


def redo_notes(ctx: RunContext[ReviewDeps], redos: list[Redo], note: Optional[str] = None) -> str:
    """Redo notes from source: copy each note's words again from the pages its blocks came from, with the plain
    look, naming the comments each redo answers. The note keeps its field; set its look again afterwards. The
    result ends with what the round has changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why."""
    deps = ctx.deps
    if not redos:
        return "Name at least one note."
    out, done = [], 0
    for r in redos:
        problem = _bad_ids(deps, r.comment_ids)
        if problem:
            out.append(f"- Note id {r.note_id}: {problem}")
            continue
        try:
            with db.connect(immediate=True) as conn, store.tagged(deps.round_id, r.comment_ids):
                store.redo_from_source(conn, deps.run_id, r.note_id, _actor(deps), reason=_reason(deps, note))
        except store.Refused as exc:
            out.append(f"- Note id {r.note_id}: not copied again. {exc}")
            continue
        done += 1
        out.append(f"- Note id {r.note_id}: copied again from its pages with the plain look.")
    if done:
        deps.writes += 1
        deps.event("redo", clean_note(note) or f"Copied {done} note(s) again from their pages.", {"notes": done})
    return "\n".join(out + ["", _report_text(deps)])


TOOLS = (show_notes, find_note_fields, move_notes, set_note_look, preview_notes, redo_notes)


# The review packet ----------------------------------------------------------------

def packet_where(conn, deps: ReviewDeps, comment) -> tuple[str, list[str]]:
    """(where a note comment points, what is saved there now), for the first message."""
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (comment["note_id"],)).fetchone()
    if row is None:
        return "a note that no longer exists", []
    part = json.loads(comment["note_part_json"]) if comment["note_part_json"] else None
    where = f"note id {row['id']}, {note_parts.note_title(row)}"
    if part:
        bits = [f"block {part['block']}"]
        if part.get("row") is not None:
            bits.append(f"row {part['row'] + 1}")
        if part.get("column") is not None:
            bits.append(f"column {part['column'] + 1}")
        shown = note_parts.part_name(json.loads(row["blocks_json"])["blocks"], part)
        where += f", {part['scope']} ({', '.join(bits)}: {shown})"
    else:
        where += ", the whole note"
    n = store.get_note(conn, deps.run_id, row["id"])
    return where, [f"Saved now: {note_heading(deps, n)} Read it with show_notes."]


def placed_lines(conn, deps: ReviewDeps) -> list[str]:
    """Every note of the run in one line each, for the first message."""
    return [f"- note id {n['id']}: {n['number'] or '(no number)'} {n['title']}, {_where(deps, n)}"
            for n in store.run_notes(conn, deps.run_id)]

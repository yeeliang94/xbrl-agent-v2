"""The note store: every write of a run's notes goes through here.

Agents and people call the same functions. Every write adds a `note_history`
row (before, after, who, round, comments, reason) and an activity event. A
refused write raises `Refused` with one plain sentence; nothing is saved.

The words of a note come only from the run's page content, copied by
`app/notes/copy.py`. Nothing here takes text from a caller: a look change
brings the whole block list back and is refused unless its words and
blocks are those already stored (`blocks.words`).

Three hard stops, and only these (docs/step-6-plan.md 6b): a note in a
heading field; a block that is not from a page of this run; a write to
another run. Everything else refused is a request that does not fit, such
as a field or note that does not exist.

No check reads the notes ("policy and disclosure notes cite the same pages"
has no shared citation to compare in v2; see `app/checks/placement_checks.py`),
so a write re-runs no checks.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence, Union

from pydantic import ValidationError

from app.db import now
from app.figures.store import Actor, Refused
from app.notes import copy as copier
from app.notes import field_text, note_figures, store_reports
from app.notes import store_rows as rows
from app.notes.blocks import NoteBody, Table, has_unsure, settled, words
from app.notes.store_rows import tagged

__all__ = ["Actor", "Refused", "NoteNotFound", "NotePlacement", "place_note", "set_look", "move_note", "replace_sources",
           "clear_note", "confirm_note", "redo_from_source", "undo_change", "restore_note", "put_back",
           "run_notes", "get_note", "prepared_text", "note_state", "note_history", "latest_change", "placed_elsewhere", "tagged",
           "ANOTHER_RUN", "LOOK_ONLY"]

ANOTHER_RUN = "That note belongs to another run, so change it from that run."
LOOK_ONLY = "A look change cannot change the note's words or blocks, so change only its look."
NO_FIELD = "There is no such note field."
NOT_PLACED = "This note is not placed, so there is no field text to copy."


class NoteNotFound(Refused):
    """A note or history entry that does not exist in this run."""


class NotPlaced(Refused):
    """A note in no field, asked for its field's text."""


@dataclass
class NotePlacement:
    """One note, or one part of a note split at a first-level sub-section."""
    number: str
    title: str
    sources: Sequence[tuple[int, int]]   # (PDF page, block index) in reading order
    node_uuid: str
    part: int = 1
    parts: int = 1
    position: Optional[int] = None       # None: last in the field
    certainty: str = "sure"
    certainty_reason: str = ""
    reason: str = ""


# Checks --------------------------------------------------------------------

def _run(conn: sqlite3.Connection, run_id: int) -> None:
    if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
        raise NoteNotFound("There is no such run.")


def _note(conn: sqlite3.Connection, run_id: int, note_id: int) -> sqlite3.Row:
    row = rows.by_id(conn, note_id)
    if row is None:
        raise NoteNotFound("There is no such note in this run.")
    if row["run_id"] != run_id:
        raise Refused(ANOTHER_RUN)
    return row


def _field(conn: sqlite3.Connection, node_uuid: str) -> sqlite3.Row:
    field = rows.field_row(conn, node_uuid)
    if field is None:
        raise Refused(NO_FIELD)
    if field["kind"] == "ABSTRACT":
        label = " ".join(field["label"].lstrip("*").split())
        raise Refused(f"{label} is a heading, so place the note in a field under it.")
    return field


def _copy(conn: sqlite3.Connection, run_id: int, sources: Iterable[tuple[int, int]]) -> NoteBody:
    try:
        blocks = copier.copy_blocks(conn, run_id, list(sources))
        return NoteBody(blocks=blocks)
    except copier.NotFromRun as exc:
        raise Refused(str(exc)) from exc
    except ValidationError as exc:
        raise Refused(_sentence(exc)) from exc
    except ValueError as exc:
        raise Refused(str(exc)) from exc


def _sentence(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "The blocks are not in the note block shape."
    message = str(errors[0].get("msg", "")).removeprefix("Value error, ")
    where = ".".join(str(p) for p in errors[0].get("loc", ()))
    if any(e.get("type") == "too_short" for e in errors[:1]) and "blocks" in where:
        return "Give at least one block for the note."
    return message if message.endswith(".") else f"{where}: {message}."


def _shape(body: NoteBody) -> list[tuple]:
    out = []
    for b in body.blocks:
        extra = (len(b.columns), len(b.rows)) if isinstance(b, Table) else ()
        out.append((b.kind, b.id, b.source.page, b.source.block, *extra))
    return out


def _pages(body: NoteBody) -> list[int]:
    return sorted({b.source.page for b in body.blocks})


def _sure(value: str) -> str:
    if value not in ("sure", "unsure"):
        raise Refused("Certainty is sure or unsure.")
    return value


# Writes --------------------------------------------------------------------

def _save(conn: sqlite3.Connection, run_id: int, note_id: Optional[int], new: dict[str, Any], action: str,
          actor: Actor, reason: str, message: str) -> dict:
    """The note after the write, with `history_id`: the history row this write added."""
    note_id, history_id = rows.write(conn, run_id, note_id, new, action=action, actor_kind=actor.kind,
                                     actor_name=actor.name, reason=reason)
    rows.event(conn, run_id, note_id, history_id, action, message)
    return {**get_note(conn, run_id, note_id), "history_id": history_id}


def place_note(conn: sqlite3.Connection, run_id: int, placement: NotePlacement, actor: Actor) -> dict:
    """Copy the source blocks into a new note placed in a field. Raises `Refused`."""
    _run(conn, run_id)
    field = _field(conn, placement.node_uuid)
    if not placement.sources:
        raise Refused("Give at least one block for the note.")
    if not 1 <= int(placement.part) <= int(placement.parts):
        raise Refused("A note's part is a number from 1 to its number of parts.")
    body = _copy(conn, run_id, placement.sources)
    position = placement.position if placement.position is not None else rows.next_position(
        conn, run_id, placement.node_uuid)
    new = {"note_number": " ".join(placement.number.split()), "title": " ".join(placement.title.split()),
           "pages": _pages(body), "template_id": field["template_id"], "node_uuid": placement.node_uuid,
           "part": int(placement.part), "parts": int(placement.parts), "position": int(position),
           "blocks": body.model_dump(mode="json"), "format_state": rows.format_state_for(body, "fine"),
           "format_reason": "", "certainty": _sure(placement.certainty),
           "certainty_reason": " ".join(placement.certainty_reason.split()), "confirmed_by": None,
           "confirmed_at": None}
    label = rows.field_label(conn, placement.node_uuid)
    split = f"part {placement.part} of {placement.parts} of " if placement.parts > 1 else ""
    return _save(conn, run_id, None, new, "place", actor, placement.reason,
                 f"Placed {split}{rows.note_name(new)} in {label}.")


def set_look(conn: sqlite3.Connection, run_id: int, note_id: int, blocks: Union[NoteBody, list, dict],
             actor: Actor, *, format_state: Optional[str] = None, format_reason: Optional[str] = None,
             reason: str = "") -> dict:
    """Change the look only. `blocks` is the note's whole block list with the
    new look; its words and blocks must be the stored ones."""
    row = _note(conn, run_id, note_id)
    try:
        if isinstance(blocks, NoteBody):
            new_body = blocks
        else:
            new_body = NoteBody.model_validate({"blocks": blocks} if isinstance(blocks, list) else blocks)
    except ValidationError as exc:
        raise Refused(_sentence(exc)) from exc
    old_body = rows.body(row)
    if words(new_body) != words(old_body) or _shape(new_body) != _shape(old_body):
        raise Refused(LOOK_ONLY)
    if format_state not in (None, "fine", "check_formatting"):
        raise Refused("The formatting state is fine or check formatting.")
    wanted = format_state or row["format_state"]
    new = {"blocks": new_body.model_dump(mode="json"), "format_state": rows.format_state_for(new_body, wanted),
           "format_reason": " ".join((format_reason if format_reason is not None else
                                      row["format_reason"] if wanted == "check_formatting" else "").split())}
    return _save(conn, run_id, note_id, new, "look", actor, reason, f"Changed the look of {rows.note_name(row)}.")


def move_note(conn: sqlite3.Connection, run_id: int, note_id: int, node_uuid: str, actor: Actor, *,
              position: Optional[int] = None, reason: str = "") -> dict:
    """Place the note in another field, last there unless `position` is given. A person who moves a note has
    chosen its field, so the move also confirms the placement (owner, 24 November 2026); its formatting and
    gaps still wait for Confirm."""
    row = _note(conn, run_id, note_id)
    field = _field(conn, node_uuid)
    if node_uuid == row["node_uuid"] and position in (None, row["position"]):
        return get_note(conn, run_id, note_id)
    if position is None:
        position = row["position"] if node_uuid == row["node_uuid"] else rows.next_position(
            conn, run_id, node_uuid, note_id)
    old = rows.field_label(conn, row["node_uuid"])
    new_label = rows.field_label(conn, node_uuid)
    message = (f"Moved {rows.note_name(row)} from {old} to {new_label}." if old
               else f"Placed {rows.note_name(row)} in {new_label}.")
    new: dict[str, Any] = {"node_uuid": node_uuid, "template_id": field["template_id"], "position": int(position)}
    if node_uuid != row["node_uuid"]:
        new.update(_placement_checked(actor) if actor.kind == "person" else _UNCHECKED)
    return _save(conn, run_id, note_id, new, "move", actor, reason, message)


def _placement_checked(actor: Actor) -> dict[str, Any]:
    return {"confirmed_by": actor.name, "confirmed_at": now(), "certainty": "sure", "certainty_reason": ""}


# An agent that puts a note in another field undoes any person's check: nobody has looked at the new field.
_UNCHECKED: dict[str, Any] = {"confirmed_by": None, "confirmed_at": None}


def confirm_placement(conn: sqlite3.Connection, run_id: int, note_id: int, actor: Actor) -> dict:
    """A person says the note's field is right. Unlike `confirm_note`, its formatting and gaps stay as they are."""
    row = _note(conn, run_id, note_id)
    if row["node_uuid"] is None:
        raise Refused("The note is in no field, so there is no field to confirm.")
    label = rows.field_label(conn, row["node_uuid"])
    return _save(conn, run_id, note_id, _placement_checked(actor), "confirm", actor, "",
                 f"Confirmed {rows.note_name(row)} belongs in {label}.")


def replace_sources(conn: sqlite3.Connection, run_id: int, note_id: int, sources: Sequence[tuple[int, int]],
                    node_uuid: str, actor: Actor, reason: str = "") -> dict:
    """Place the note again from other source blocks, copied with the plain look, in `node_uuid`. A
    history row keeps the blocks it had."""
    row = _note(conn, run_id, note_id)
    field = _field(conn, node_uuid)
    if not sources:
        raise Refused("Give at least one block for the note.")
    body = _copy(conn, run_id, sources)
    position = row["position"] if node_uuid == row["node_uuid"] else rows.next_position(conn, run_id, node_uuid,
                                                                                        note_id)
    new = {"blocks": body.model_dump(mode="json"), "pages": _pages(body), "node_uuid": node_uuid,
           "template_id": field["template_id"], "position": int(position),
           "format_state": rows.format_state_for(body, "fine"), "format_reason": ""}
    if node_uuid != row["node_uuid"] and actor.kind != "person":
        new.update(_UNCHECKED)
    label = rows.field_label(conn, node_uuid)
    return _save(conn, run_id, note_id, new, "place", actor, reason,
                 f"Placed {rows.note_name(row)} again, from other blocks, in {label}.")


def clear_note(conn: sqlite3.Connection, run_id: int, note_id: int, actor: Actor, reason: str = "") -> dict:
    """Take the note out of its field. It stays in the run's notes, not placed, with its blocks."""
    row = _note(conn, run_id, note_id)
    if row["node_uuid"] is None:
        return get_note(conn, run_id, note_id)
    label = rows.field_label(conn, row["node_uuid"]) or "its field"
    return _save(conn, run_id, note_id, {"node_uuid": None, "template_id": None, "position": 0}, "clear", actor,
                 reason, f"Took {rows.note_name(row)} out of {label}.")


def confirm_note(conn: sqlite3.Connection, run_id: int, note_id: int, actor: Actor) -> dict:
    """Record who checked the note: its placement becomes sure, its formatting fine. A person's confirm also
    marks every "not sure" look done (in the same history row, so undo brings them back) and settles the
    source gaps reported for it (recorded on that row, so undo opens them again)."""
    row = _note(conn, run_id, note_id)
    new = {"confirmed_by": actor.name, "confirmed_at": now(), "certainty": "sure", "certainty_reason": "",
           "format_state": "fine", "format_reason": ""}
    body = rows.body(row)
    if actor.kind == "person" and has_unsure(body):
        new["blocks"] = settled(body).model_dump(mode="json")
    out = _save(conn, run_id, note_id, new, "confirm", actor, "", f"Confirmed {rows.note_name(row)}.")
    if actor.kind == "person":
        done = store_reports.settle_gaps(conn, run_id, note_id, actor.name)
        if done:
            conn.execute("UPDATE note_history SET settled_reports_json = ? WHERE id = ?",
                         (json.dumps(done), out["history_id"]))
    return out


def redo_from_source(conn: sqlite3.Connection, run_id: int, note_id: int, actor: Actor, reason: str = "") -> dict:
    """Copy the note's blocks again from the pages they came from, with the
    plain look. The note keeps its field."""
    row = _note(conn, run_id, note_id)
    sources = [(b.source.page, b.source.block) for b in rows.body(row).blocks]
    body = _copy(conn, run_id, sources)
    return _save(conn, run_id, note_id, {"blocks": body.model_dump(mode="json"), "pages": _pages(body),
                                          "format_state": rows.format_state_for(body, "fine"),
                                          "format_reason": ""}, "redo", actor, reason,
                 f"Copied {rows.note_name(row)} again from its pages.")


def _entry(conn: sqlite3.Connection, run_id: int, history_id: int) -> sqlite3.Row:
    entry = conn.execute("SELECT * FROM note_history WHERE id = ?", (history_id,)).fetchone()
    if entry is None:
        raise NoteNotFound("There is no such change in this note's history.")
    if entry["run_id"] != run_id:
        raise Refused(ANOTHER_RUN)
    return entry


def _put(conn: sqlite3.Connection, run_id: int, row: sqlite3.Row, snapshot: Optional[dict], actor: Actor,
         reason: str) -> dict:
    """Write a recorded state back exactly. None (the note was new) takes the
    note out of its field and keeps its blocks: a real note is never dropped."""
    if snapshot is None:
        new = {"node_uuid": None, "template_id": None, "position": 0}
    else:
        new = {name: snapshot[name] for name in rows.STATE_FIELDS}
    return _save(conn, run_id, row["id"], new, "restore", actor, reason,
                 f"Put {rows.note_name(row)} back as it was.")


def undo_change(conn: sqlite3.Connection, run_id: int, history_id: int, actor: Actor, reason: str = "") -> dict:
    """Put the note back exactly as it was before one change."""
    entry = _entry(conn, run_id, history_id)
    row = _note(conn, run_id, entry["note_id"])
    out = _put(conn, run_id, row, json.loads(entry["before_json"]) if entry["before_json"] else None, actor,
               reason)
    store_reports.reopen_settled(conn, run_id, json.loads(entry["settled_reports_json"] or "[]"))
    return out


def restore_note(conn: sqlite3.Connection, run_id: int, history_id: int, actor: Actor, reason: str = "") -> dict:
    """Put the note back exactly as it was after one change."""
    entry = _entry(conn, run_id, history_id)
    return _put(conn, run_id, _note(conn, run_id, entry["note_id"]), json.loads(entry["after_json"]), actor, reason)


def put_back(conn: sqlite3.Connection, run_id: int, states: Sequence[tuple[int, Optional[dict]]],
             actor: Actor) -> list[dict]:
    """Undo of a round: put each note back to a recorded state (`before` of
    its history), or out of its field when that state is None. One "restore"
    history row each. Raises `Refused` before writing if any note is not this run's."""
    found = [_note(conn, run_id, note_id) for note_id, _ in states]
    done = [_put(conn, run_id, row, state, actor, "")["id"] for row, (_, state) in zip(found, states)]
    return [get_note(conn, run_id, note_id) for note_id in dict.fromkeys(done)]


# Reads ---------------------------------------------------------------------

def get_note(conn: sqlite3.Connection, run_id: int, note_id: int, *, fit: bool = False) -> dict:
    """`Note`. With `fit`, as a person reads it: its field's fit to mTool's limit, and the figures of a
    numeric note."""
    row = _note(conn, run_id, note_id)
    out = rows.public(conn, row)
    if fit:
        out["fit"] = field_text.fit(field_text.prepared(conn, run_id, row["node_uuid"])) if row["node_uuid"] else None
        out["figures"] = note_figures.note_figures(conn, run_id, row["template_id"])
    return out


def run_notes(conn: sqlite3.Connection, run_id: int, *, blocks: bool = False, fit: bool = False) -> list[dict]:
    """The run's notes by template, field, position and id; not placed ones last. With `fit`, each carries its
    field's fit to mTool's limit."""
    _run(conn, run_id)
    out, fits = [], {}
    house = field_text.house(conn) if fit else None
    for r in conn.execute("SELECT * FROM notes WHERE run_id = ? ORDER BY node_uuid IS NULL, template_id, node_uuid, "
                          "position, id", (run_id,)):
        shown = rows.public(conn, r, blocks=blocks)
        if fit:
            uuid = r["node_uuid"]
            if uuid and uuid not in fits:
                fits[uuid] = field_text.fit(field_text.prepared(conn, run_id, uuid, house))
            shown["fit"] = fits.get(uuid) if uuid else None
        out.append(shown)
    return out


def prepared_text(conn: sqlite3.Connection, run_id: int, note_id: int) -> dict:
    """`PreparedNote`: the note's field's whole text as mTool gets it."""
    row = _note(conn, run_id, note_id)
    text = field_text.prepared(conn, run_id, row["node_uuid"]) if row["node_uuid"] else None
    if text is None:
        raise NotPlaced(NOT_PLACED)
    return field_text.public(row["node_uuid"], text)


def note_state(conn: sqlite3.Connection, run_id: int, note_id: int) -> Optional[dict]:
    """A note as history records it."""
    return rows.state(_note(conn, run_id, note_id))


def note_history(conn: sqlite3.Connection, run_id: int, note_id: int) -> list[dict]:
    _note(conn, run_id, note_id)
    return [rows.history_entry(r) for r in conn.execute(
        "SELECT * FROM note_history WHERE note_id = ? ORDER BY id", (note_id,))]


def latest_change(conn: sqlite3.Connection, run_id: int, note_id: int) -> int:
    _note(conn, run_id, note_id)
    found = conn.execute("SELECT MAX(id) FROM note_history WHERE note_id = ?", (note_id,)).fetchone()[0]
    if found is None:
        raise NoteNotFound("There is no such change in this note's history.")
    return int(found)


def placed_elsewhere(conn: sqlite3.Connection, run_id: int, sources: Iterable[tuple[int, int]]) -> list[dict]:
    """The run's placed notes that already hold any of these source blocks,
    for the notes agent's "already placed" feedback."""
    wanted = {(int(p), int(b)) for p, b in sources}
    out = []
    for r in conn.execute("SELECT * FROM notes WHERE run_id = ? AND node_uuid IS NOT NULL ORDER BY id", (run_id,)):
        held = {(b.source.page, b.source.block) for b in rows.body(r).blocks}
        if held & wanted:
            out.append(rows.public(conn, r, blocks=False))
    return out

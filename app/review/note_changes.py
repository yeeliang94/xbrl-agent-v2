"""What a correction round changed in the notes, counted by the server from
note history (decision record 3, item 7), beside the figures' count in
`changes.py`.

Every note write a round makes carries the round's id and the comments it
served (`app/notes/store_rows.tagged`). From those rows: each note as it was
before the round's first write on it, and as it is now, in plain words. The
agent's own claim is never the proof.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from app.notes import store_rows as rows
from app.notes.blocks import parse, words

_STATES = {"fine": "fine", "check_formatting": "check formatting", "not_sure": "not sure"}


@dataclass
class NoteTouched:
    first_row: int
    last_row: int
    before: Optional[dict]          # the note before the round; None when the round placed it
    served: set = field(default_factory=set)
    actions: set = field(default_factory=set)


def touched(conn: sqlite3.Connection, round_id: int) -> dict[int, NoteTouched]:
    """Every note the round wrote, by note id."""
    out: dict[int, NoteTouched] = {}
    for r in conn.execute("SELECT id, note_id, action, before_json, comment_ids_json FROM note_history "
                          "WHERE round_id = ? ORDER BY id", (round_id,)):
        entry = out.get(r["note_id"])
        if entry is None:
            entry = out[r["note_id"]] = NoteTouched(r["id"], r["id"],
                                                    json.loads(r["before_json"]) if r["before_json"] else None)
        entry.last_row = r["id"]
        entry.actions.add(r["action"])
        entry.served.update(json.loads(r["comment_ids_json"] or "[]"))
    return out


def own_note(comment: sqlite3.Row) -> Optional[int]:
    return comment["note_id"] if comment["target_kind"] == "note" else None


def _field(conn: sqlite3.Connection, state: Optional[dict]) -> Optional[dict]:
    uuid = (state or {}).get("node_uuid")
    return {"node_uuid": uuid, "label": rows.field_label(conn, uuid) or ""} if uuid else None


def _label(place: Optional[dict]) -> str:
    return place["label"] if place else "not placed"


def differences(conn: sqlite3.Connection, before: Optional[dict], now: Optional[dict],
                actions: set) -> list[str]:
    """Every difference a person sees between two states of a note, in plain words."""
    before, now = before or {}, now or {}
    out = []
    if before.get("node_uuid") != now.get("node_uuid"):
        out.append(f"field {_label(_field(conn, before))} → {_label(_field(conn, now))}")
    elif before.get("position") != now.get("position"):
        out.append("position changed")
    if before.get("blocks") != now.get("blocks"):
        same_words = bool(before.get("blocks")) and bool(now.get("blocks")) and \
            words(parse(before["blocks"])) == words(parse(now["blocks"]))
        out.append("copied again from its pages" if "redo" in actions or not same_words else "look changed")
    if before.get("format_state") != now.get("format_state") and before:
        out.append(f"formatting {_STATES.get(before.get('format_state'), before.get('format_state'))} → "
                   f"{_STATES.get(now.get('format_state'), now.get('format_state'))}")
    if before.get("confirmed_at") != now.get("confirmed_at") and now.get("confirmed_at"):
        out.append("confirmed")
    return out


def change(conn: sqlite3.Connection, note_id: int, entry: Optional[NoteTouched]) -> dict:
    """`NoteChange` (docs/api-contract.md, Step 6e)."""
    now = rows.state(rows.by_id(conn, note_id))
    before = entry.before if entry else now
    found = differences(conn, before, now, entry.actions) if entry is not None else []
    return {"note_id": note_id, "number": (now or {}).get("note_number", ""), "title": (now or {}).get("title", ""),
            "field_was": _field(conn, before), "field_now": _field(conn, now), "changed": bool(found),
            "differences": found, "served": sorted(entry.served) if entry else []}


def _name(c: dict) -> str:
    number = f"note {c['number']} " if c["number"] else "the note "
    return f"{number}{c['title']} (note id {c['note_id']})"


def text_lines(comment_notes: dict[int, list[dict]], other: list[dict]) -> list[str]:
    """The notes part of the report the Reviewer reads after each change."""
    out = []
    for comment_id, notes in comment_notes.items():
        moved = [n for n in notes if n["changed"]]
        if moved:
            out.append(f"- Comment {comment_id}, notes: " + "; ".join(
                f"{_name(n)}: {', '.join(n['differences'])}" for n in moved) + ".")
    if other:
        out.append("Other notes changed, which no comment points at:")
        out += [f"- {_name(n)}: {', '.join(n['differences'])}"
                + (f" (written for comment {', '.join(map(str, n['served']))})" if n["served"]
                   else " (written for no comment)") for n in other]
    return out

"""Low-level note rows, history and events. Used only inside the note store."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional, Sequence

from app.db import now
from app.notes.blocks import NoteBody, has_unsure, parse
from app.runs import events

# The correction round and comments the writes in a block serve (see `tagged`).
_TAG: ContextVar[Optional[tuple[int, tuple[int, ...]]]] = ContextVar("note_write_tag", default=None)

# What history records of a note, and what undo puts back exactly.
STATE_FIELDS = ("note_number", "title", "pages", "template_id", "node_uuid", "part", "parts", "position",
                "blocks", "format_state", "format_reason", "certainty", "certainty_reason", "confirmed_by",
                "confirmed_at")
_JSON_FIELDS = {"pages": "pages_json", "blocks": "blocks_json"}

EVENT_SOURCE = "notes"


@contextmanager
def tagged(round_id: int, comment_ids: Sequence[int] = ()) -> Iterator[None]:
    """Every note history row written in this block carries the round's id
    and the comments it served."""
    token = _TAG.set((int(round_id), tuple(sorted({int(c) for c in comment_ids}))))
    try:
        yield
    finally:
        _TAG.reset(token)


def by_id(conn: sqlite3.Connection, note_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()


def state(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    """A note as history records it."""
    if row is None:
        return None
    out: dict[str, Any] = {}
    for name in STATE_FIELDS:
        column = _JSON_FIELDS.get(name)
        out[name] = json.loads(row[column]) if column else row[name]
    return out


def body(row: sqlite3.Row) -> NoteBody:
    return parse(json.loads(row["blocks_json"]))


def format_state_for(body_: NoteBody, wanted: str) -> str:
    """A note with a "not sure" look shows as not sure until that look is set;
    an explicit "check formatting" stays."""
    if wanted == "check_formatting":
        return wanted
    return "not_sure" if has_unsure(body_) else "fine"


def write(conn: sqlite3.Connection, run_id: int, note_id: Optional[int], new: dict[str, Any], *, action: str,
          actor_kind: str, actor_name: str, reason: str = "") -> tuple[int, int]:
    """Insert (note_id None) or update one note to the state `new`, and add a
    history row. Returns (note id, history id)."""
    existing = by_id(conn, note_id) if note_id is not None else None
    before = state(existing)
    stamp = now()
    columns = {(_JSON_FIELDS.get(k) or k): (json.dumps(v, ensure_ascii=False) if k in _JSON_FIELDS else v)
               for k, v in new.items()}
    columns.update(updated_by=actor_name, updated_at=stamp)
    if existing is None:
        columns.update(run_id=run_id, created_at=stamp)
        cur = conn.execute(f"INSERT INTO notes({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                           list(columns.values()))
        note_id = int(cur.lastrowid)
    else:
        conn.execute(f"UPDATE notes SET {', '.join(f'{k} = ?' for k in columns)}, revision = revision + 1 "
                     "WHERE id = ?", [*columns.values(), note_id])
    after = state(by_id(conn, note_id))
    tag = _TAG.get()
    cur = conn.execute(
        "INSERT INTO note_history(note_id, run_id, action, actor_kind, actor_name, before_json, after_json, "
        "round_id, comment_ids_json, reason, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (note_id, run_id, action, actor_kind, actor_name,
         json.dumps(before, ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False),
         tag[0] if tag else None, json.dumps(list(tag[1])) if tag else None, _one_line(reason), stamp))
    return note_id, int(cur.lastrowid)


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())[:500]


def field_row(conn: sqlite3.Connection, node_uuid: Optional[str]) -> Optional[sqlite3.Row]:
    """A field a note can go in, with its template id, label and kind (LEAF or ABSTRACT): a prose-note field
    (`notes_nodes`), or the text field of a numeric note (issued capital, related parties), which lives in the
    concept tables beside its figures (`app/catalog/note_fields.py`)."""
    if not node_uuid:
        return None
    found = conn.execute("SELECT node_uuid, template_id, label, kind FROM notes_nodes WHERE node_uuid = ?",
                         (node_uuid,)).fetchone()
    if found is not None:
        return found
    from app.catalog.note_fields import numeric_text_field   # the catalogue owns what a text field is
    return numeric_text_field(conn, node_uuid)


def field_label(conn: sqlite3.Connection, node_uuid: Optional[str]) -> Optional[str]:
    row = field_row(conn, node_uuid)
    return " ".join(row["label"].lstrip("*").split()) if row is not None else None


def next_position(conn: sqlite3.Connection, run_id: int, node_uuid: str, leave_out: Optional[int] = None) -> int:
    found = conn.execute("SELECT MAX(position) FROM notes WHERE run_id = ? AND node_uuid = ? AND id != ?",
                         (run_id, node_uuid, leave_out or 0)).fetchone()[0]
    return 0 if found is None else int(found) + 1


def note_name(row_or_state) -> str:
    number, title = row_or_state["note_number"], row_or_state["title"]
    if number:
        return f"note {number} {title}".rstrip()
    return f"the note {title}".rstrip() if title else "the note"


def event(conn: sqlite3.Connection, run_id: int, note_id: int, history_id: int, action: str,
          message: str) -> None:
    row = by_id(conn, note_id)
    events.insert(conn, EVENT_SOURCE, action, message, run_id=run_id,
                  data={"note_id": note_id, "history_id": history_id, "action": action},
                  pages=json.loads(row["pages_json"]))


_LEAD = re.compile(r"^\s*(?:\d+(?:\.\d+)+\.?|\d+\.|\(?[a-z]{1,4}\)|\d+\s*\(?[a-z]{1,4}\))\s+", re.I)


def part_title(row: sqlite3.Row, note_body) -> str:
    """What a part of a split note is about: its first heading that is not the note's own, without its
    numbering ("(k) Borrowing costs" reads "Borrowing costs"). Empty for a whole note, or a part with no
    heading of its own, such as the note's opening paragraph."""
    if row["parts"] < 2:
        return ""
    own = " ".join(row["title"].split()).lower()
    for b in note_body.blocks:
        if b.kind != "heading":
            continue
        text = " ".join(b.text.split())
        if own and own in text.lower():
            continue
        return _LEAD.sub("", text).strip()
    return ""


def public(conn: sqlite3.Connection, row: sqlite3.Row, *, blocks: bool = True) -> dict[str, Any]:
    """`Note` (or `NoteSummary` without blocks), as docs/api-contract.md Step 6b."""
    label = field_label(conn, row["node_uuid"])
    note_body = body(row)
    out = {
        "id": row["id"], "number": row["note_number"], "title": row["title"],
        "pages": json.loads(row["pages_json"]), "template_id": row["template_id"],
        "field": {"node_uuid": row["node_uuid"], "label": label or ""} if row["node_uuid"] else None,
        "part": row["part"], "parts": row["parts"], "part_title": part_title(row, note_body),
        "position": row["position"],
        "format_state": row["format_state"], "format_reason": row["format_reason"],
        "has_unsure": has_unsure(note_body), "certainty": row["certainty"],
        "certainty_reason": row["certainty_reason"], "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"], "revision": row["revision"], "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }
    if blocks:
        out["blocks"] = note_body.model_dump(mode="json")["blocks"]
    return out


def history_entry(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "action": row["action"], "actor_kind": row["actor_kind"],
            "actor_name": row["actor_name"], "changed_at": row["changed_at"], "round_id": row["round_id"],
            "comment_ids": json.loads(row["comment_ids_json"]) if row["comment_ids_json"] else [],
            "reason": row["reason"],
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"])}

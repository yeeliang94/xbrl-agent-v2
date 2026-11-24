"""The notes agent's coverage record (`note_reports`): a capture problem, a
mandatory field the source does not support, or a note routed to another
template where it is really placed. Every report adds an activity event.

Part of the note store: nothing else writes `note_reports`.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional, Sequence

from app.db import now
from app.notes.source import plain_number
from app.notes.store_rows import EVENT_SOURCE, field_row
from app.runs import events

KINDS = ("source_gap", "missing_mandatory_field", "routed_elsewhere")
_WORDS = {"source_gap": "a capture problem", "missing_mandatory_field": "a required field the report does not support",
          "routed_elsewhere": "a note placed in another template"}


class ReportRefused(ValueError):
    """`str()` is one plain sentence; `status` the HTTP status the routes answer with."""

    def __init__(self, sentence: str, status: int = 404) -> None:
        super().__init__(sentence)
        self.status = status


def add_report(conn: sqlite3.Connection, run_id: int, kind: str, *, note_number: str = "",
               node_uuid: Optional[str] = None, pages: Sequence[int] = (), reason: str, actor_name: str,
               message: Optional[str] = None, after_block: Optional[str] = None) -> int:
    """Record one report. `message` is the activity row a person reads; by default it names the kind."""
    if kind not in KINDS:
        raise ReportRefused("A report is a source gap, a missing mandatory field or a note routed elsewhere.", 422)
    reason = " ".join(str(reason or "").split())[:1000]
    if not reason:
        raise ReportRefused("Give the reason in one plain sentence.", 422)
    clean_pages = sorted({int(p) for p in pages if type(p) is int and p >= 1})
    number = " ".join(str(note_number or "").split())
    cur = conn.execute(
        "INSERT INTO note_reports(run_id, kind, note_number, node_uuid, pages_json, reason, actor_name, after_block, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, kind, number, node_uuid, json.dumps(clean_pages), reason, actor_name,
         " ".join(str(after_block).split()).lower() or None if after_block else None, now()))
    report_id = int(cur.lastrowid)
    shown = message or (f"Reported {_WORDS[kind]}" + (f" for note {number}" if number else "") + ".")
    events.insert(conn, EVENT_SOURCE, "reported", shown, run_id=run_id,
                  data={"report_id": report_id, "kind": kind, "note_number": number}, pages=clean_pages)
    return report_id


def run_reports(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """The run's reports, oldest first, as rows."""
    out = []
    for r in conn.execute("SELECT * FROM note_reports WHERE run_id = ? ORDER BY id", (run_id,)):
        row = dict(r)
        row["pages"] = json.loads(row.pop("pages_json") or "[]")
        out.append(row)
    return out


def report_note_id(conn: sqlite3.Connection, run_id: int, note_number: str) -> Optional[int]:
    """The run's note with this printed number (its first part), or None."""
    wanted = plain_number(note_number)
    if not wanted:
        return None
    for r in conn.execute("SELECT id, note_number FROM notes WHERE run_id = ? ORDER BY part, id", (run_id,)):
        if plain_number(r["note_number"]) == wanted:
            return int(r["id"])
    return None


def public(conn: sqlite3.Connection, row: dict) -> dict:
    """`NoteReport` (docs/api-contract.md, Step 6e)."""
    field = field_row(conn, row["node_uuid"])
    return {"id": row["id"], "kind": row["kind"], "note_id": report_note_id(conn, row["run_id"], row["note_number"]),
            "note_number": row["note_number"], "node_uuid": row["node_uuid"],
            "field_label": " ".join(field["label"].lstrip("*").split()) if field else None,
            "template_id": field["template_id"] if field else None, "pages": row["pages"], "reason": row["reason"],
            "after_block": row["after_block"], "status": row["status"], "settled_by": row["settled_by"],
            "settled_at": row["settled_at"], "created_at": row["created_at"]}


def public_reports(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [public(conn, r) for r in run_reports(conn, run_id)]


def _one(conn: sqlite3.Connection, run_id: int, report_id: int) -> dict:
    found = next((r for r in run_reports(conn, run_id) if r["id"] == report_id), None)
    if found is None:
        raise ReportRefused("There is no such report in this run.")
    return found


def _set_status(conn: sqlite3.Connection, run_id: int, report_id: int, status: str, who: Optional[str],
                message: str) -> dict:
    stamp = now() if status == "settled" else None
    conn.execute("UPDATE note_reports SET status = ?, settled_by = ?, settled_at = ? WHERE id = ?",
                 (status, who, stamp, report_id))
    found = _one(conn, run_id, report_id)
    events.insert(conn, EVENT_SOURCE, "report", message, run_id=run_id,
                  data={"report_id": report_id, "kind": found["kind"], "status": status}, pages=found["pages"])
    return public(conn, found)


def leave_empty(conn: sqlite3.Connection, run_id: int, report_id: int, email: str) -> dict:
    """A person settles a report: leaves a missing required field empty, or accepts a capture problem as it
    is (also one whose note was never placed, which no confirm can reach)."""
    found = _one(conn, run_id, report_id)
    if found["kind"] == "missing_mandatory_field":
        label = public(conn, found)["field_label"] or "the field"
        return _set_status(conn, run_id, report_id, "settled", email, f"Left {label} empty.")
    if found["kind"] == "source_gap":
        what = f"note {found['note_number']}" if found["note_number"] else "the notes"
        return _set_status(conn, run_id, report_id, "settled", email,
                           f"Accepted the capture problem reported for {what}.")
    raise ReportRefused("Only a missing required field or a capture problem can be settled.", 422)


def reopen(conn: sqlite3.Connection, run_id: int, report_id: int) -> dict:
    found = _one(conn, run_id, report_id)
    shown = public(conn, found)
    what = shown["field_label"] or (f"note {found['note_number']}" if found["note_number"] else "the report")
    return _set_status(conn, run_id, report_id, "open", None, f"Opened the report on {what} again.")


def settle_gaps(conn: sqlite3.Connection, run_id: int, note_id: int, email: str) -> list[int]:
    """A person's confirm of a note, or of any part of a split note, settles the open source gaps reported
    for it. Returns the reports it settled."""
    row = conn.execute("SELECT note_number FROM notes WHERE id = ?", (note_id,)).fetchone()
    number = plain_number(row["note_number"]) if row else ""
    if not number:
        return []
    done = []
    for r in run_reports(conn, run_id):
        if r["kind"] == "source_gap" and r["status"] == "open" and plain_number(r["note_number"]) == number:
            _set_status(conn, run_id, r["id"], "settled", email,
                        f"Settled the capture problem reported for note {r['note_number']}.")
            done.append(int(r["id"]))
    return done


def reopen_settled(conn: sqlite3.Connection, run_id: int, report_ids: Sequence[int]) -> None:
    """Undo of a confirm: the reports it settled, still settled, are open again."""
    for r in run_reports(conn, run_id):
        if r["id"] in set(report_ids) and r["status"] == "settled":
            reopen(conn, run_id, r["id"])

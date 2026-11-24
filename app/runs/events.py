"""Progress rows in the `events` table. The browser asks for rows after id N.

Each row may name the PDF pages its step concerns (`pages`), so the
activity can link to them; the message stays one plain sentence.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Optional

from app import db

MAX_LIMIT = 500


def add_event(
    source: str,
    kind: str,
    message: str,
    *,
    run_id: Optional[int] = None,
    job_id: Optional[int] = None,
    data: Optional[dict[str, Any]] = None,
    pages: Optional[Iterable[int]] = None,
) -> int:
    with db.connect() as conn:
        return insert(conn, source, kind, message, run_id=run_id, job_id=job_id, data=data, pages=pages)


MAX_NOTE = 300
# Rows the browser may leave out: the shared loop's own bookkeeping.
INTERNAL = ("step", "tool")


def clean_note(note: Any) -> Optional[str]:
    """An agent's note on a step as one line, or None."""
    text = " ".join(note.split()) if isinstance(note, str) else ""
    if not text:
        return None
    return text if len(text) <= MAX_NOTE else text[:MAX_NOTE - 1].rstrip() + "…"


def clean_pages(pages: Optional[Iterable[Any]]) -> list[int]:
    """Page numbers, once each, in order. Anything that is not a whole number is left out."""
    return sorted({int(p) for p in (pages or []) if type(p) is int and p > 0})


def insert(conn: sqlite3.Connection, source: str, kind: str, message: str, *, run_id: Optional[int] = None,
           job_id: Optional[int] = None, data: Optional[dict[str, Any]] = None,
           pages: Optional[Iterable[int]] = None) -> int:
    """One event in the caller's transaction."""
    found = clean_pages(pages)
    cur = conn.execute(
        "INSERT INTO events(run_id, job_id, source, kind, message, data_json, pages_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, job_id, source, kind, message, json.dumps(data, default=str) if data else None,
         json.dumps(found) if found else None, db.now()))
    return int(cur.lastrowid)


def _pages(row: sqlite3.Row) -> list[int]:
    return json.loads(row["pages_json"]) if row["pages_json"] else []


def figure_pages(conn: sqlite3.Connection, run_id: int, keys: Iterable[tuple]) -> list[int]:
    """The printed pages behind figures, by (concept_uuid, period, entity_scope)."""
    pages: set[int] = set()
    for uuid, period, entity in keys:
        if not uuid:
            continue
        sql = ("SELECT DISTINCT l.page FROM figure_lines l JOIN figures f ON f.id = l.figure_id WHERE f.run_id = ? "
               "AND f.concept_uuid = ? AND f.entity_scope = ?")
        params = [run_id, uuid, entity or "Company"]
        if period:
            sql, params = sql + " AND f.period = ?", params + [period]
        pages.update(r[0] for r in conn.execute(sql, params))
    return sorted(pages)


def list_events(*, run_id: Optional[int] = None, after_id: int = 0) -> list[dict[str, Any]]:
    """Every event after `after_id`, with its data. For the job worker and tests."""
    sql = "SELECT * FROM events WHERE id > ?"
    params: list[Any] = [after_id]
    if run_id is not None:
        sql += " AND run_id = ?"
        params.append(run_id)
    with db.connect() as conn:
        rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    return [
        {**dict(r), "data": json.loads(r["data_json"]) if r["data_json"] else None, "pages": _pages(r)}
        for r in rows
    ]


def page_events(conn: sqlite3.Connection, run_id: int, after_id: int, limit: int, *,
                hide_internal: bool = False) -> dict[str, Any]:
    """One page of a run's activity, oldest first, without the data payloads.

    Page forward by passing the returned `last_id` as the next `after_id`.
    `has_data` says whether `event_detail` has more to show.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    rows = conn.execute(
        "SELECT id, job_id, source, kind, message, created_at, pages_json, "
        "json_extract(data_json, '$.question_id') AS question_id, data_json IS NOT NULL AS has_data "
        f"FROM events WHERE run_id = ? AND id > ? {'AND kind NOT IN (?, ?)' if hide_internal else ''} "
        "ORDER BY id LIMIT ?",
        (run_id, after_id, *(INTERNAL if hide_internal else ()), limit + 1)).fetchall()
    page = [{**{k: r[k] for k in ("id", "job_id", "source", "kind", "message", "created_at")},
             "pages": _pages(r), "question_id": r["question_id"], "has_data": bool(r["has_data"])}
            for r in rows[:limit]]
    return {"events": page, "last_id": page[-1]["id"] if page else after_id,
            "has_more": len(rows) > limit}


def event_detail(conn: sqlite3.Connection, run_id: int, event_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM events WHERE run_id = ? AND id = ?", (run_id, event_id)).fetchone()
    if row is None:
        return None
    out = {k: row[k] for k in ("id", "job_id", "source", "kind", "message", "created_at")}
    out["data"] = json.loads(row["data_json"]) if row["data_json"] else None
    out["pages"] = _pages(row)
    out["question_id"] = (out["data"] or {}).get("question_id")
    return out

"""Low-level figure rows, lines and history. Used only inside the figure store."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional, Sequence

from app.db import now
from app.figures._hard_stops import Line

# The correction round and comments the writes in a block serve (see `tagged`).
_TAG: ContextVar[Optional[tuple[int, tuple[int, ...]]]] = ContextVar("figure_write_tag", default=None)

STATE_FIELDS = ("concept_uuid", "value", "status", "children_status", "origin", "stated_value",
                "locked", "certainty", "reason", "sign_question", "person_edited")


@contextmanager
def tagged(round_id: int, comment_ids: Sequence[int] = ()) -> Iterator[None]:
    """Every history row written in this block, totals recalculated included,
    carries the round's id and the comments it served."""
    token = _TAG.set((int(round_id), tuple(sorted({int(c) for c in comment_ids}))))
    try:
        yield
    finally:
        _TAG.reset(token)


def lines_of(conn: sqlite3.Connection, figure_id: int) -> list[Line]:
    return [Line(r["printed_label"], r["page"], r["amount"], r["print_order"], r["coefficient"], r["section"])
            for r in conn.execute("SELECT * FROM figure_lines WHERE figure_id = ? ORDER BY id", (figure_id,))]


def state(conn: sqlite3.Connection, row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    """A figure as history records it: its fields and its printed lines."""
    if row is None:
        return None
    out = {name: row[name] for name in STATE_FIELDS}
    out["lines"] = [vars(line) for line in lines_of(conn, row["id"])]
    return out


def get(conn: sqlite3.Connection, run_id: int, concept_uuid: str, period: str, entity_scope: str,
        dimension_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ? "
        "AND entity_scope = ? AND dimension_key = ?",
        (run_id, concept_uuid, period, entity_scope, dimension_key)).fetchone()


def by_id(conn: sqlite3.Connection, run_id: int, figure_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM figures WHERE run_id = ? AND id = ?", (run_id, figure_id)).fetchone()


def write(conn: sqlite3.Connection, run_id: int, key: tuple[str, str, str, str], fields: dict[str, Any],
          lines: Optional[Sequence[Line]], *, action: str, actor_kind: str, actor_name: str) -> int:
    """Insert or update one figure, replace its lines if given, and add a history row."""
    concept_uuid, period, entity_scope, dimension_key = key
    existing = get(conn, run_id, *key)
    before = state(conn, existing)
    stamp = now()
    if existing is None:
        columns = {"run_id": run_id, "concept_uuid": concept_uuid, "period": period,
                   "entity_scope": entity_scope, "dimension_key": dimension_key,
                   "status": "observed", "origin": actor_kind, **fields,
                   "updated_by": actor_name, "updated_at": stamp}
        names = ", ".join(columns)
        cur = conn.execute(f"INSERT INTO figures({names}) VALUES ({', '.join('?' * len(columns))})",
                           list(columns.values()))
        figure_id = int(cur.lastrowid)
    else:
        figure_id = existing["id"]
        sets = {**fields, "updated_by": actor_name, "updated_at": stamp}
        conn.execute(
            f"UPDATE figures SET {', '.join(f'{k} = ?' for k in sets)}, revision = revision + 1 WHERE id = ?",
            [*sets.values(), figure_id])
    if lines is not None:
        conn.execute("DELETE FROM figure_lines WHERE figure_id = ?", (figure_id,))
        conn.executemany(
            "INSERT INTO figure_lines(figure_id, printed_label, print_order, page, amount, coefficient, "
            "section) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(figure_id, line.printed_label.strip(), int(line.print_order), int(line.page), line.amount,
              float(line.coefficient), line.section.strip()) for line in lines])
    after = state(conn, by_id(conn, run_id, figure_id))
    tag = _TAG.get()
    conn.execute(
        "INSERT INTO figure_history(run_id, figure_id, action, actor_kind, actor_name, changed_at, "
        "before_json, after_json, round_id, comment_ids_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, figure_id, action, actor_kind, actor_name, stamp,
         json.dumps(before) if before else None, json.dumps(after),
         tag[0] if tag else None, json.dumps(list(tag[1])) if tag else None))
    return figure_id


def typed_import(row: Optional[sqlite3.Row]) -> bool:
    """A this-year figure imported from the starting workbook, whoever changed it since (hard stop 9)."""
    return row is not None and row["period"] == "CY" and bool(row["source_ref"])

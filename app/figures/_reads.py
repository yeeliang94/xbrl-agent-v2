"""The figure store's reads of a run's figures, as the store and its callers see them. Used through
`app.figures.store`."""
from __future__ import annotations

import sqlite3

from app.figures import _rows


def public(conn: sqlite3.Connection, row: sqlite3.Row, *, lines: bool = True) -> dict:
    out = {
        "id": row["id"], "concept_uuid": row["concept_uuid"], "period": row["period"],
        "entity_scope": row["entity_scope"], "dimension_key": row["dimension_key"],
        "value": None if row["status"] == "not_disclosed" else row["value"],
        "status": row["status"], "children_status": row["children_status"], "origin": row["origin"],
        "stated_value": row["stated_value"], "locked": bool(row["locked"]),
        "certainty": row["certainty"], "reason": row["reason"],
        "sign_question": bool(row["sign_question"]), "person_edited": bool(row["person_edited"]),
        "revision": row["revision"], "updated_by": row["updated_by"], "updated_at": row["updated_at"],
    }
    if lines:
        out["lines"] = [vars(line) for line in _rows.lines_of(conn, row["id"])]
    return out


def run_figures(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [public(conn, r) for r in conn.execute(
        "SELECT * FROM figures WHERE run_id = ? ORDER BY id", (run_id,))]


def current_figures(conn: sqlite3.Connection, run_id: int, entity_scope: str) -> dict[tuple[str, str], dict]:
    """The run's figures for one entity, with no category, by (concept, period).
    Each is shaped as in `run_figures`, without its lines; a blank figure's
    value is None."""
    return {(r["concept_uuid"], r["period"]): public(conn, r, lines=False) for r in conn.execute(
        "SELECT * FROM figures WHERE run_id = ? AND entity_scope = ? AND dimension_key = '' ORDER BY id",
        (run_id, entity_scope))}

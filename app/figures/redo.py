"""Clearing one statement's figures so its agent can fill it again ("Redo statement").

What a person settled is told apart from what the agent left: a figure a
person edited, or confirmed as it stands now, is the person's. The person
choosing the redo says whether those are kept. A figure imported from a
starting workbook is never cleared here: it is not the agent's work. Each
clear goes through the store's own write, so it has a history row naming the
person who asked for the redo, and the totals and checks follow.
"""
from __future__ import annotations

import sqlite3

from typing import Optional

from app.catalog import lookup
from app.catalog.statements import StatementType
from app.figures import store
from app.figures.store import Actor, Refused, _apply, _family, _write_from

# A change to the figure itself. A confirm made after the last of these still stands.
_CHANGES = ("save", "edit", "clear", "move", "restore", "import")


def _filled(conn: sqlite3.Connection, run_id: int, template_id: str) -> list[sqlite3.Row]:
    """The statement's figures that hold something, or that a person left blank on purpose, and did not come
    from a starting workbook."""
    return conn.execute(
        "SELECT f.* FROM figures f JOIN concept_nodes n ON n.concept_uuid = f.concept_uuid "
        "WHERE f.run_id = ? AND n.template_id = ? AND f.locked = 0 AND f.source_ref IS NULL "
        "AND ((f.origin IN ('agent', 'person') AND f.value IS NOT NULL AND f.status != 'not_disclosed') "
        "OR (f.origin = 'calculated' AND f.stated_value IS NOT NULL) OR f.person_edited = 1) ORDER BY f.id",
        (run_id, template_id)).fetchall()


def _confirmed(conn: sqlite3.Connection, run_id: int) -> set[int]:
    """Figures a person confirmed and nobody has changed since."""
    marks = ", ".join("?" * len(_CHANGES))
    return {r[0] for r in conn.execute(
        "SELECT h.figure_id FROM figure_history h WHERE h.run_id = ? AND h.action = 'confirm' "
        "AND h.actor_kind = 'person' AND h.id > COALESCE((SELECT MAX(c.id) FROM figure_history c "
        f"WHERE c.figure_id = h.figure_id AND c.action IN ({marks})), 0)", (run_id, *_CHANGES))}


def kept_by_person(conn: sqlite3.Connection, run_id: int, template_id: str) -> list[dict]:
    """The statement's figures a person edited or confirmed: `{figure_id, concept_uuid, period, entity_scope,
    label, how}` with `how` "edited" or "confirmed", in the order they were first saved."""
    confirmed = _confirmed(conn, run_id)
    out = []
    for row in _filled(conn, run_id, template_id):
        how = "edited" if row["person_edited"] else "confirmed" if row["id"] in confirmed else None
        if how is None:
            continue
        concept = lookup.concept(conn, row["concept_uuid"])
        out.append({"figure_id": row["id"], "concept_uuid": row["concept_uuid"], "period": row["period"],
                    "entity_scope": row["entity_scope"], "label": concept.plain_label if concept else "", "how": how})
    return out


def held(conn: sqlite3.Connection, run_id: int, redo: Optional[dict]) -> list[int]:
    """The ids of the figures an open redo (`progress.open_redo`) keeps as they are now: what a person edited
    or confirmed in that statement, when they chose to keep it. Worked out afresh, so a figure a person
    corrected after a stopped redo is kept through the retry too."""
    family = lookup.run_family(conn, run_id)
    if not redo or not redo["keep_mine"] or family is None:
        return []
    template_id = family.template_ids.get(StatementType(redo["statement"]))
    return [k["figure_id"] for k in kept_by_person(conn, run_id, template_id)] if template_id else []


def clear_statement(conn: sqlite3.Connection, run_id: int, template_id: str, email: str, reason: str, *,
                    keep: frozenset[int] = frozenset()) -> int:
    """Clear the statement's figures except those whose ids are in `keep`. Returns how many were cleared."""
    family = _family(conn, run_id)
    actor, cleared = Actor("person", email), 0
    for row in _filled(conn, run_id, template_id):
        if row["id"] in keep:
            continue
        write = _write_from(row, value=None, lines=[], certainty="sure", reason=reason, total=None)
        conn.execute("SAVEPOINT redo_clear")
        try:
            # Recorded as the person's change, but the figure is the agent's to fill again.
            _apply(conn, family, write, actor, "clear", kept={
                "person_edited": 0, "origin": "agent" if row["origin"] == "person" else row["origin"]})
            conn.execute("RELEASE redo_clear")
            cleared += 1
        except Refused:
            conn.execute("ROLLBACK TO redo_clear")
            conn.execute("RELEASE redo_clear")
    if cleared:
        store.recalculate(conn, run_id)
    return cleared

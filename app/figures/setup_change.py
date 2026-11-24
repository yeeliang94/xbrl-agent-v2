"""Clearing the figures agent's work when a person's answer changes the setup.

A changed standard, level, year end or unit refiles the whole run, and a
changed layout refiles one statement, so the figures the agent saved there
are cleared before extraction starts again. A figure a person typed or
edited is never cleared, nor one imported from last year's workbook. Each
clear goes through the store's own write, so it has a history row naming
the person whose answer caused it, and the totals and checks follow.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

from app.figures import store
from app.figures.store import Actor, FigureWrite, Refused, _apply, _family, _write_from


def clear_agent_figures(conn: sqlite3.Connection, run_id: int, template_ids: Iterable[str], email: str,
                        reason: str) -> int:
    """Clear, in the run's current templates, every figure the agent saved
    (a value, or a total's printed amount) that no person changed. Use before
    the setup itself changes, while the figures still belong to the run's
    templates. Returns how many were cleared."""
    ids = sorted(set(template_ids))
    if not ids:
        return 0
    family = _family(conn, run_id)
    rows = conn.execute(
        "SELECT f.* FROM figures f JOIN concept_nodes n ON n.concept_uuid = f.concept_uuid "
        f"WHERE f.run_id = ? AND n.template_id IN ({','.join('?' * len(ids))}) AND f.person_edited = 0 "
        "AND f.locked = 0 AND ((f.origin = 'agent' AND f.value IS NOT NULL AND f.status != 'not_disclosed') "
        "OR (f.origin = 'calculated' AND f.stated_value IS NOT NULL)) ORDER BY f.id", (run_id, *ids)).fetchall()
    actor, cleared = Actor("person", email), 0
    for row in rows:
        write: FigureWrite = _write_from(row, value=None, lines=[], certainty="sure", reason=reason, total=None)
        conn.execute("SAVEPOINT setup_clear")
        try:
            # Recorded as the person's change, but not as a person's edit: the figure stays the agent's to fill.
            _apply(conn, family, write, actor, "clear", kept={"person_edited": 0, "origin": row["origin"]})
            conn.execute("RELEASE setup_clear")
            cleared += 1
        except Refused:
            conn.execute("ROLLBACK TO setup_clear")
            conn.execute("RELEASE setup_clear")
    if cleared:
        store.recalculate(conn, run_id)
    return cleared

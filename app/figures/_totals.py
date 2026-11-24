"""Add up every total from its lines and save the sums.

Copied in logic from v1 `concept_model/cascade.py` (`recompute_after_turn`),
adapted to v2's `figures` table. Rules carried over:

- A total marked as having no breakdown (`aggregate_only`) keeps its typed value.
- Blank lines count as zero once at least one line under the total has a
  number. A total with no numeric line at all stays blank, never zero.
- Sums are rounded to cents and compared with a cent tolerance.
- Every change to a saved sum adds a history row.

v1 also kept an observed value on an ordinary total and raised a conflict
when its parts disagreed. v2 cannot store such a value (the store refuses
it), and keeps the printed amount in `stated_value` instead, so a total and
its parts never need forcing together.
"""
from __future__ import annotations

import logging
import sqlite3

from app.catalog.lookup import RunFamily, edges_for
from app.figures import _rows
from app.figures.sums import CENT, add_up, known_value, money

logger = logging.getLogger(__name__)


def recalculate_totals(conn: sqlite3.Connection, family: RunFamily) -> int:
    """Recompute every total in the run. Returns how many sums changed."""
    edges = edges_for(conn, family.all_template_ids())
    if not edges:
        return 0
    facts: dict[tuple, dict] = {}
    scopes: set[tuple[str, str, str]] = set()
    for r in conn.execute("SELECT concept_uuid, period, entity_scope, dimension_key, value, status, "
                          "children_status FROM figures WHERE run_id = ?", (family.run_id,)):
        facts[(r[0], r[1], r[2], r[3])] = {"value": known_value(r[4], r[5]), "children_status": r[6]}
        scopes.add((r[1], r[2], r[3]))
    changed_total = 0
    for period, entity_scope, dims in sorted(scopes):
        if period not in family.periods:
            continue

        def value_of(child, p=period, e=entity_scope, d=dims):
            return (facts.get((child, p, e, d)) or {}).get("value")

        changed, passes = True, 50
        while changed and passes > 0:
            changed, passes = False, passes - 1
            for parent, children in edges.items():
                key = (parent, period, entity_scope, dims)
                parent_fact = facts.get(key)
                if parent_fact and parent_fact["children_status"] == "aggregate_only":
                    continue
                new_value = add_up(children, value_of)
                existing = parent_fact["value"] if parent_fact else None
                if new_value is None:
                    if existing is None:
                        continue
                    # its lines were all cleared: clear the total too
                elif existing is not None and abs(money(existing) - new_value) <= CENT:
                    continue
                fields = {"value": new_value,
                          "status": "observed" if new_value is not None else "not_disclosed",
                          "children_status": "itemised"}
                if parent_fact is None:
                    fields["origin"] = "calculated"
                _rows.write(conn, family.run_id, key, fields, None, action="calculate",
                            actor_kind="calculated", actor_name="")
                facts[key] = {"value": new_value, "children_status": "itemised"}
                changed = True
                changed_total += 1
        if changed and passes == 0:
            logger.warning("Totals did not settle for run %s %s %s; the sums may be incomplete.",
                           family.run_id, period, entity_scope)
    return changed_total


def parts_sum(conn: sqlite3.Connection, run_id: int, concept_uuid: str, period: str,
              entity_scope: str, dimension_key: str) -> float | None:
    """What a total's direct lines add up to, or None when none has a number."""
    def value_of(child):
        row = _rows.get(conn, run_id, child, period, entity_scope, dimension_key)
        return known_value(row["value"], row["status"]) if row is not None else None

    children = conn.execute("SELECT child_uuid, coefficient FROM concept_edges WHERE parent_uuid = ?",
                            (concept_uuid,)).fetchall()
    return add_up(((c[0], c[1]) for c in children), value_of)

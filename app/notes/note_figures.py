"""The figures under a numeric note (issued capital, related parties), for the
note's page in review.

A note placed in a numeric note's text field shows that note's figures below
its words. They are figures, read through the figure store, laid out in the
Statement shapes the review grid already draws (`app/figures/views.py`): one
row per field and category holding a figure, in template order, a column per
entity and year.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from app.catalog import lookup
from app.figures import store, views


def _member_words(member: str) -> str:
    local = member.split("_", 1)[-1].removesuffix("Member")
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local)
    return words[:1].upper() + words[1:].lower()


def _category(dimension_key: str) -> str:
    if not dimension_key:
        return ""
    try:
        members = json.loads(dimension_key).values()
    except (ValueError, AttributeError):
        return ""
    return ", ".join(_member_words(str(m)) for m in members)


NUMERIC = ("ISSUED_CAPITAL", "RELATED_PARTY")


def numeric_code(family: Optional[lookup.RunFamily], template_id: Optional[str]) -> Optional[str]:
    """ISSUED_CAPITAL or RELATED_PARTY for a numeric note's template, else None."""
    if family is None or not template_id:
        return None
    return next((code for code, t in family.note_template_ids.items() if t == template_id and code in NUMERIC),
                None)


def holding_note(conn: sqlite3.Connection, run_id: int, template_id: Optional[str]) -> Optional[int]:
    """The note placed in a numeric note's text field, whose page shows that note's figures, or None."""
    if not template_id:
        return None
    row = conn.execute("SELECT id FROM notes WHERE run_id = ? AND template_id = ? ORDER BY position, id LIMIT 1",
                       (run_id, template_id)).fetchone()
    return int(row[0]) if row else None


def note_figures(conn: sqlite3.Connection, run_id: int, template_id: Optional[str]) -> Optional[dict]:
    """`{"columns", "rows", "unsure"}` for a numeric note's template, or None for any other template."""
    family = lookup.run_family(conn, run_id)
    if not (family and template_id and template_id in family.note_template_ids.values()):
        return None
    concepts = {c.concept_uuid: c for c in lookup.template_concepts(conn, template_id)}
    grouped: dict[tuple[str, str], dict] = {}
    ids = [r[0] for r in conn.execute(
        f"SELECT id FROM figures WHERE run_id = ? AND concept_uuid IN ({','.join('?' * len(concepts))})",
        (run_id, *concepts))] if concepts else []
    for f in (store.get_figure(conn, run_id, i) for i in ids):
        grouped.setdefault((f["concept_uuid"], f["dimension_key"]), {})[(f["entity_scope"], f["period"])] = f
    columns = views._columns(family)
    rows, unsure = [], 0
    order = sorted(grouped, key=lambda k: (concepts[k[0]].sheet, concepts[k[0]].row, k[1]))
    for uuid, dimension in order:
        concept, found = concepts[uuid], grouped[(uuid, dimension)]
        cells = {c["key"]: views._cell(found.get((c["entity_scope"], c["period"])), concept) for c in columns}
        unsure += sum(1 for cell in cells.values() if cell["figure_id"] and cell["certainty"] == "unsure")
        category = _category(dimension)
        label = f"{concept.plain_label}, {category}" if category else concept.plain_label
        first = next((f for f in found.values() if f.get("lines")), None)
        line = first["lines"][0] if first else None
        rows.append(views._row("total" if concept.is_total else "line", label, concept.plain_label, cells, set(),
                               concept_uuid=uuid, sheet=concept.sheet, row=concept.row,
                               page=line["page"] if line else None, print_order=None,
                               printed_label=line["printed_label"] if line else None))
    return {"columns": columns, "rows": rows, "unsure": unsure}

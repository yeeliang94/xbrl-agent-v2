"""The numeric fields of a run's templates, with what each one is.

One read of the catalogue, shared by the workbook reader, the comparison and
the mTool fill.
Text fields (notes) and headings are left out: they hold no number.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from app.catalog.lookup import RunFamily, edges_for

NOTE_NAMES = {"ISSUED_CAPITAL": "Share capital", "RELATED_PARTY": "Related parties"}
STATEMENT_ORDER = ("SOFP", "SOPL", "SOCI", "SOCF", "SOCIE", "Share capital", "Related parties")


@dataclass(frozen=True)
class FieldInfo:
    concept_uuid: str
    template_id: str
    statement: str
    kind: str                     # LEAF | MATRIX_CELL | COMPUTED
    label: str                    # the template's label, as in column A
    sheet: str
    row: int
    matrix_col: Optional[str]
    matrix_col_label: Optional[str]
    is_total: bool                # the template calculates it from other lines
    primary: str                  # the SSM element name, or '' when it has none
    dimensions: dict = field(default_factory=dict, hash=False)   # fixed categories (the equity column)

    @property
    def plain_label(self) -> str:
        return self.label.lstrip("*").strip()


def run_fields(conn: sqlite3.Connection, family: RunFamily) -> dict[str, FieldInfo]:
    """{concept_uuid: FieldInfo} for every numeric field of the run's templates."""
    names = {t: s.value for s, t in family.template_ids.items()}
    names.update({t: NOTE_NAMES[n] for n, t in family.note_template_ids.items()})
    if not names:
        return {}
    marks = ",".join("?" * len(names))
    totals = set(edges_for(conn, set(names)))
    out: dict[str, FieldInfo] = {}
    for r in conn.execute(
            "SELECT n.concept_uuid, n.template_id, n.kind, n.canonical_label, n.render_sheet, n.render_row, "
            "n.matrix_col, n.matrix_col_label, COALESCE(a.primary_concept, '') AS primary_concept, "
            "COALESCE(a.dimensions_json, '{}') AS dims, "
            "EXISTS (SELECT 1 FROM template_slots s WHERE s.canonical_target_id = n.concept_uuid "
            "AND s.value_kind = 'html') AS text, COALESCE(t.data_type, '') AS data_type "
            "FROM concept_nodes n LEFT JOIN concept_semantic_addresses a ON a.concept_uuid = n.concept_uuid "
            "LEFT JOIN taxonomy_concepts t ON t.source_element_id = a.primary_concept "
            f"WHERE n.template_id IN ({marks}) AND n.is_current = 1 "
            "AND n.kind IN ('LEAF', 'MATRIX_CELL', 'COMPUTED') ORDER BY n.template_id, n.render_sheet, "
            "n.render_row, n.matrix_col", sorted(names)):
        if r["text"] or r["data_type"].lower().endswith("textblockitemtype"):
            continue
        out[r["concept_uuid"]] = FieldInfo(
            r["concept_uuid"], r["template_id"], names[r["template_id"]], r["kind"], r["canonical_label"],
            r["render_sheet"], r["render_row"], r["matrix_col"], r["matrix_col_label"],
            r["kind"] == "COMPUTED" or r["concept_uuid"] in totals, r["primary_concept"], json.loads(r["dims"]))
    return out


def run_edges(conn: sqlite3.Connection, family: RunFamily) -> dict[str, list[tuple[str, float]]]:
    return edges_for(conn, family.all_template_ids())

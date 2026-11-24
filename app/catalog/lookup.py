"""Read-only questions about the catalogue and a run's templates.

The figure store, the checks and the statement views ask these. Nothing here
writes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from app.catalog.parser import derive_template_id
from app.catalog.statements import StatementType, numeric_note_path, template_path


@dataclass(frozen=True)
class Concept:
    concept_uuid: str
    template_id: str
    kind: str
    label: str
    sheet: str
    row: int
    matrix_col: Optional[str]
    matrix_col_label: Optional[str]
    is_total: bool          # owns a formula: its value is added up from its children
    writable: bool          # the manifest has a writable slot for it
    text: bool              # a text disclosure, saved as a note

    @property
    def plain_label(self) -> str:
        return self.label.lstrip("*").strip()


@dataclass
class RunFamily:
    run_id: int
    standard: str            # mfrs | mpers
    level: str               # company | group
    first_statements: bool
    variants: dict[StatementType, str] = field(default_factory=dict)
    template_ids: dict[StatementType, str] = field(default_factory=dict)
    note_template_ids: dict[str, str] = field(default_factory=dict)

    @property
    def entity_scopes(self) -> tuple[str, ...]:
        return ("Group", "Company") if self.level == "group" else ("Company",)

    @property
    def periods(self) -> tuple[str, ...]:
        return ("CY",) if self.first_statements else ("CY", "PY")

    def all_template_ids(self) -> set[str]:
        return set(self.template_ids.values()) | set(self.note_template_ids.values())

    def statement_of(self, template_id: str) -> Optional[StatementType]:
        return next((s for s, t in self.template_ids.items() if t == template_id), None)


def run_family(conn: sqlite3.Connection, run_id: int) -> Optional[RunFamily]:
    run = conn.execute(
        "SELECT r.id, r.standard, r.level, COALESCE(s.first_statements, 0) AS first_statements "
        "FROM runs r LEFT JOIN run_setup s ON s.run_id = r.id WHERE r.id = ?", (run_id,)).fetchone()
    if run is None:
        return None
    if run["standard"] is None or run["level"] is None:
        # Still being read: setup has not chosen the standard or level, so the
        # run has no templates yet.
        return RunFamily(run_id, "", "", bool(run["first_statements"]))
    family = RunFamily(run_id, run["standard"].lower(), run["level"].lower(), bool(run["first_statements"]))
    # A statement switched off at setup has no template: nothing is extracted or checked for it.
    for row in conn.execute("SELECT statement, variant FROM run_statements WHERE run_id = ? AND included = 1",
                            (run_id,)):
        statement = StatementType(row["statement"])
        family.variants[statement] = row["variant"]
        try:
            path = template_path(statement, row["variant"], family.level, family.standard)
        except (ValueError, KeyError):
            continue  # NotPrepared or a layout this standard does not have
        family.template_ids[statement] = derive_template_id(path)
    for note in ("ISSUED_CAPITAL", "RELATED_PARTY"):
        family.note_template_ids[note] = derive_template_id(
            numeric_note_path(note, family.level, family.standard))
    return family


_CONCEPT_SQL = (
    "SELECT n.concept_uuid, n.template_id, n.kind, n.canonical_label, n.render_sheet, n.render_row, "
    "n.matrix_col, n.matrix_col_label, "
    "(n.kind = 'COMPUTED' OR EXISTS (SELECT 1 FROM concept_edges e WHERE e.parent_uuid = n.concept_uuid)) "
    "AS is_total, "
    "EXISTS (SELECT 1 FROM template_slots s WHERE s.canonical_target_id = n.concept_uuid "
    "AND s.validation_status = 'writable') AS writable, "
    "EXISTS (SELECT 1 FROM template_slots s WHERE s.canonical_target_id = n.concept_uuid "
    "AND s.value_kind = 'html') AS text "
    "FROM concept_nodes n"
)


def _concept(row: sqlite3.Row) -> Concept:
    return Concept(row["concept_uuid"], row["template_id"], row["kind"], row["canonical_label"],
                   row["render_sheet"], row["render_row"], row["matrix_col"], row["matrix_col_label"],
                   bool(row["is_total"]), bool(row["writable"]), bool(row["text"]))


def concept(conn: sqlite3.Connection, concept_uuid: str) -> Optional[Concept]:
    row = conn.execute(_CONCEPT_SQL + " WHERE n.concept_uuid = ? AND n.is_current = 1",
                       (concept_uuid,)).fetchone()
    return _concept(row) if row else None


def template_concepts(conn: sqlite3.Connection, template_id: str) -> list[Concept]:
    """Every current line of one template, top to bottom."""
    return [_concept(r) for r in conn.execute(
        _CONCEPT_SQL + " WHERE n.template_id = ? AND n.is_current = 1 ORDER BY n.render_row, n.matrix_col",
        (template_id,))]


def edges_for(conn: sqlite3.Connection, template_ids: set[str]) -> dict[str, list[tuple[str, float]]]:
    """{total: [(child, coefficient)]} for the given templates."""
    if not template_ids:
        return {}
    marks = ",".join("?" * len(template_ids))
    out: dict[str, list[tuple[str, float]]] = {}
    for parent, child, coefficient in conn.execute(
            "SELECT e.parent_uuid, e.child_uuid, e.coefficient FROM concept_edges e "
            f"JOIN concept_nodes n ON n.concept_uuid = e.parent_uuid WHERE n.template_id IN ({marks})",
            sorted(template_ids)):
        out.setdefault(parent, []).append((child, float(coefficient)))
    return out


def row_totals(conn: sqlite3.Connection, template_ids: set[str]) -> set[str]:
    """Matrix totals added up across their own row only: every line they add
    sits on the same sheet and row (the equity statement's component totals,
    v1 `receipt.py` `horizontal_input_total`)."""
    if not template_ids:
        return set()
    marks = ",".join("?" * len(template_ids))
    return {r[0] for r in conn.execute(
        "SELECT n.concept_uuid FROM concept_nodes n JOIN concept_edges e ON e.parent_uuid = n.concept_uuid "
        "JOIN concept_nodes child ON child.concept_uuid = e.child_uuid "
        f"WHERE n.template_id IN ({marks}) AND n.is_current = 1 AND n.kind = 'MATRIX_CELL' "
        "GROUP BY n.concept_uuid "
        "HAVING SUM(child.render_row != n.render_row OR child.render_sheet != n.render_sheet) = 0",
        sorted(template_ids))}


def aliases_for(conn: sqlite3.Connection, template_id: str) -> list[tuple[str, str, int]]:
    """Face rows that show a sub-sheet total: (concept, sheet, row)."""
    return [(r[0], r[1], r[2]) for r in conn.execute(
        "SELECT a.concept_uuid, a.alias_sheet, a.alias_row FROM concept_render_aliases a "
        "JOIN concept_nodes n ON n.concept_uuid = a.concept_uuid "
        "WHERE n.template_id = ? AND n.is_current = 1", (template_id,))]


def template_targets(conn: sqlite3.Connection, concept_uuids: set[str]
                     ) -> dict[tuple[str, str, str], tuple[str, int, str]]:
    """{(concept, entity, period): (sheet, row, column)}: where each field sits in the app's own template."""
    if not concept_uuids:
        return {}
    marks = ",".join("?" * len(concept_uuids))
    return {(r[0], r[1], r[2]): (r[3], r[4], r[5]) for r in conn.execute(
        "SELECT concept_uuid, entity_scope, period, target_sheet, target_row, target_col FROM concept_targets "
        f"WHERE concept_uuid IN ({marks})", sorted(concept_uuids))}


def template_aliases(conn: sqlite3.Connection, concept_uuids: set[str]) -> list[tuple[str, str, int, str]]:
    """Face cells that repeat a sub-sheet total in the app's own template: (concept, sheet, row, column)."""
    if not concept_uuids:
        return []
    marks = ",".join("?" * len(concept_uuids))
    return [(r[0], r[1], r[2], r[3]) for r in conn.execute(
        "SELECT concept_uuid, alias_sheet, alias_row, alias_col FROM concept_render_aliases "
        f"WHERE concept_uuid IN ({marks})", sorted(concept_uuids))]

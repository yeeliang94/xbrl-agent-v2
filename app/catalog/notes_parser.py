"""Read a prose-note template into `notes_nodes` rows.

Copied from v1 `concept_model/notes_parser.py` (`NotesNode`,
`parse_notes_template`) and `concept_model/notes_importer.py`
(`import_notes_template`). The prose templates (Corporate information,
Accounting policies, List of notes) are flat label lists with no formulas:
every labelled row is a heading or a fillable field. A row is a heading when
it is styled as one or its taxonomy element is not reportable, the same rule
the statement parser uses. IDs use the statement parser's scheme (UUID5 of
template, sheet, row and label), so v2's IDs equal v1's.

Changes from v1: the parser reads the template's sheets itself (v1 went
through its agents' template reader), each row also carries its depth under
its headings, and the import takes the caller's connection and updates rows
in place rather than deleting them all, so a placed note keeps its field.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import openpyxl

from app.catalog.manifest import MANIFEST_VERSION
from app.catalog.parser import derive_template_id, mint_uuid
from app.catalog.section_headers import discover_section_headers, keyword_fallback_for_sheet
from app.catalog.taxonomy import field_depths, semantic_addresses_for
from app.utils.paths import safe_path


@dataclass(frozen=True)
class NotesNode:
    node_uuid: str
    template_id: str
    sheet: str
    row: int
    label: str                  # as printed, a leading "*" marks a mandatory field
    kind: str                   # ABSTRACT (heading) | LEAF (fillable)
    slot_role: str              # PRESENTATION_ONLY | INPUT
    taxonomy_element_id: str | None
    depth: int | None           # 0 for the template's title; None when the template drifted


def parse_notes_template(xlsx_path: str | Path) -> tuple[str, list[NotesNode]]:
    """Every labelled column-A row of the template, top to bottom."""
    path = Path(xlsx_path)
    template_id = derive_template_id(path)
    addresses = semantic_addresses_for(str(path.resolve()))
    depths = field_depths(str(path.resolve()))
    wb = openpyxl.load_workbook(safe_path(path), data_only=False)
    nodes: list[NotesNode] = []
    try:
        for ws in wb.worksheets:
            styled = {h.row for h in discover_section_headers(
                ws, extra_keywords=keyword_fallback_for_sheet(ws.title))}
            for row in range(1, ws.max_row + 1):
                value = ws.cell(row=row, column=1).value
                label = str(value).strip() if value is not None else ""
                if not label:
                    continue
                address = addresses.get((ws.title, row, None))
                fillable = row not in styled and bool(address and address.get("reportable"))
                nodes.append(NotesNode(
                    node_uuid=mint_uuid(template_id, ws.title, row, label),
                    template_id=template_id, sheet=ws.title, row=row, label=label,
                    kind="LEAF" if fillable else "ABSTRACT",
                    slot_role="INPUT" if fillable else "PRESENTATION_ONLY",
                    taxonomy_element_id=address.get("primary_concept") if address else None,
                    depth=depths.get((ws.title, row)),
                ))
    finally:
        wb.close()
    return template_id, nodes


def import_notes_template(conn: sqlite3.Connection, template_id: str, nodes: Sequence[NotesNode]) -> int:
    """Make the template's `notes_nodes` rows equal `nodes`. Rows whose label
    or position changed get a new ID and the old row goes; unchanged rows are
    updated in place, so anything that points at them stays valid."""
    keep = [n.node_uuid for n in nodes]
    marks = ",".join("?" * len(keep)) or "''"
    conn.execute(f"DELETE FROM notes_nodes WHERE template_id = ? AND node_uuid NOT IN ({marks})",
                 (template_id, *keep))
    conn.executemany(
        "INSERT INTO notes_nodes(node_uuid, template_id, sheet, row, label, kind, slot_role, "
        "taxonomy_element_id, xbrl_concept_id, manifest_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(node_uuid) DO UPDATE SET sheet = excluded.sheet, row = excluded.row, "
        "label = excluded.label, kind = excluded.kind, slot_role = excluded.slot_role, "
        "taxonomy_element_id = excluded.taxonomy_element_id, xbrl_concept_id = excluded.xbrl_concept_id, "
        "manifest_version = excluded.manifest_version",
        [(n.node_uuid, n.template_id, n.sheet, n.row, n.label, n.kind, n.slot_role,
          n.taxonomy_element_id, n.taxonomy_element_id, MANIFEST_VERSION) for n in nodes],
    )
    return len(nodes)

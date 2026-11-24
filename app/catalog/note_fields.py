"""The note fields a run can fill, in one call.

The notes agent's field tools and the notes screens read this list. It holds
every field of the run's three prose-note templates (`notes_nodes`) and the
text field of each numeric note (issued capital, related parties), which
lives in the concept tables beside its figures. Headings are in the list,
marked, so a reader sees each field under its headings; a note never goes
into one.

New in v2. v1 rebuilt this list in several places and found the catch-all
field by its label; here the mark comes from `statements.CATCH_ALL_ELEMENTS`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.catalog.lookup import run_family
from app.catalog.parser import derive_template_id
from app.catalog.statements import CATCH_ALL_ELEMENTS, NOTE_TEMPLATES, PROSE_NOTES, prose_note_path
from app.catalog.taxonomy import field_depths


@dataclass(frozen=True)
class NoteField:
    field_id: str                 # notes_nodes.node_uuid; for a numeric note, its concept_uuid
    template: str                 # CORP_INFO | ACC_POLICIES | LIST_OF_NOTES | ISSUED_CAPITAL | RELATED_PARTY
    template_name: str            # "List of notes"
    template_id: str              # mfrs-company-notes-listofnotes-v1
    sheet: str
    row: int
    label: str                    # as printed, without the mandatory "*"
    path: tuple[str, ...]         # the rows above it, outermost first
    heading: bool                 # a heading never holds a note
    mandatory: bool               # the template marks it with "*"
    catch_all: bool               # where a note goes when no other field fits the whole of it
    taxonomy_element_id: str | None


def _plain(label: str) -> str:
    return label.lstrip("*").strip()


def _prose_fields(conn: sqlite3.Connection, note: str, level: str, standard: str) -> list[NoteField]:
    path = prose_note_path(note, level, standard)
    template_id = derive_template_id(path)
    depths = field_depths(str(path.resolve()))
    catch_all = "_" + CATCH_ALL_ELEMENTS[note]
    fields: list[NoteField] = []
    above: list[tuple[int, str]] = []   # (depth, label) of the open rows above
    for r in conn.execute("SELECT node_uuid, sheet, row, label, kind, taxonomy_element_id FROM notes_nodes "
                          "WHERE template_id = ? ORDER BY sheet, row", (template_id,)):
        depth = depths.get((r["sheet"], r["row"]), 1)
        while above and above[-1][0] >= depth:
            above.pop()
        heading = r["kind"] != "LEAF"
        element = r["taxonomy_element_id"] or ""
        fields.append(NoteField(
            r["node_uuid"], note, NOTE_TEMPLATES[note], template_id, r["sheet"], r["row"], _plain(r["label"]),
            tuple(label for _, label in above), heading, r["label"].lstrip().startswith("*"),
            not heading and element.endswith(catch_all), r["taxonomy_element_id"]))
        above.append((depth, _plain(r["label"])))
    return fields


# A numeric note's text field: the writable HTML slot of a current concept.
_TEXT_SLOT = "WHERE n.is_current = 1 AND s.value_kind = 'html' AND s.validation_status = 'writable'"


def _numeric_text_fields(conn: sqlite3.Connection, note: str, template_id: str) -> list[NoteField]:
    labels = {r["concept_uuid"]: (r["canonical_label"], r["parent_uuid"]) for r in conn.execute(
        "SELECT concept_uuid, canonical_label, parent_uuid FROM concept_nodes "
        "WHERE template_id = ? AND is_current = 1", (template_id,))}
    fields = []
    for r in conn.execute(
            "SELECT n.concept_uuid, n.render_sheet, n.render_row, n.canonical_label, n.parent_uuid, "
            "s.taxonomy_element_id FROM concept_nodes n JOIN template_slots s ON s.canonical_target_id = n.concept_uuid "
            f"{_TEXT_SLOT} AND n.template_id = ? ORDER BY n.render_row", (template_id,)):
        path, parent = [], r["parent_uuid"]
        while parent in labels:
            path.insert(0, _plain(labels[parent][0]))
            parent = labels[parent][1]
        fields.append(NoteField(
            r["concept_uuid"], note, NOTE_TEMPLATES[note], template_id, r["render_sheet"], r["render_row"],
            _plain(r["canonical_label"]), tuple(path), False, r["canonical_label"].lstrip().startswith("*"),
            False, r["taxonomy_element_id"]))
    return fields


def numeric_text_field(conn: sqlite3.Connection, node_uuid: str) -> Optional[sqlite3.Row]:
    """A numeric note's text field by its concept, as the note store reads a field: node_uuid, template_id,
    label and kind (always LEAF). None when the concept is no numeric note's text field."""
    return conn.execute(
        "SELECT n.concept_uuid AS node_uuid, n.template_id, n.canonical_label AS label, 'LEAF' AS kind "
        f"FROM concept_nodes n JOIN template_slots s ON s.canonical_target_id = n.concept_uuid {_TEXT_SLOT} "
        "AND n.concept_uuid = ? LIMIT 1", (node_uuid,)).fetchone()


def run_note_fields(conn: sqlite3.Connection, run_id: int) -> list[NoteField]:
    """Every note field of the run's standard and level, headings included,
    template by template in reading order, top to bottom. Empty for a run
    that does not exist or whose standard and level are not chosen yet."""
    family = run_family(conn, run_id)
    if family is None or not family.standard:
        return []
    fields: list[NoteField] = []
    for note in NOTE_TEMPLATES:
        if note in PROSE_NOTES:
            fields.extend(_prose_fields(conn, note, family.level, family.standard))
        else:
            fields.extend(_numeric_text_fields(conn, note, family.note_template_ids[note]))
    return fields

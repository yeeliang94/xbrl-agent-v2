"""Each note field's prepared text into mTool's note store.

Rebuilt from v1 `mtool/notes_exporter.py` (`build_notes_fill_doc`) and the
taxonomy branch of v1 `fill_footnotes`. The text is the field's prepared
text (`app/notes/field_text.prepared`), the very text the review screen
shows and the Copy button copies; nothing is rendered again here.

A field's cell is found by its SSM name on its own sheet, never by its label:
the row that carries the name, in the sheet's `#PRIM#` label column, and the
text-block cell one column to its right, as mTool lays it out. No row, or
more than one, is listed and nothing is written.

The text-block cell is locked on mTool's protected note sheets. Only mTool's
own "[Text block added]" marker goes there, never a value, in the shape v1
proved inside mTool (5 July 2026); the text itself goes in the hidden note
store. Only a Windows run in mTool can confirm the note opens as written.

`plan_notes` is pure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from app.catalog.note_fields import NoteField
from app.workbook.mtool_layout import MARKER_LABEL, Occurrences, marker_rows
from app.workbook.xlsx_cells import Cells, col_to_idx, idx_to_col, resolve_sheet_name, split_ref

if TYPE_CHECKING:
    from app.notes.render import Prepared

NOTE_REASONS = {
    "written": "Written into mTool's note store and read back.",
    "too_long": "The text is over mTool's limit, so it was not written. Split the note to fit.",
    "no_sheet": "The template has no sheet for this note.",
    "no_note_cell": "The template has no text block for this field.",
    "ambiguous": "More than one row in the template carries this field's name, so none was chosen.",
    "formula": "The template works this cell out with a formula, so it was not typed over.",
    "read_back": "The filled file does not hold the text written, so check this note.",
    "not_written": "The note could not be written into the template.",
    "duplicate_key": "mTool's note store holds this note's key twice, so mTool would open it empty. Check the template.",
}


@dataclass
class NotePlan:
    items: list[dict] = field(default_factory=list)       # for the patcher's `fill_footnotes`
    skipped: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)


def label_column(cells: Cells, row: int) -> Optional[str]:
    """The label column of the mTool table the row sits in: the nearest label marker above it. A sheet with
    more than one table (the auditors' report and its auditor table) marks each table's own."""
    above = [r for r in marker_rows(cells).get(MARKER_LABEL, []) if r <= row]
    if not above:
        return None
    columns = {col for col, (_, text) in cells.get(max(above), {}).items() if (text or "").strip() == MARKER_LABEL}
    return next(iter(columns)) if len(columns) == 1 else None


def text_block_cell(note_field: NoteField, cells: dict[str, Cells], occurrences: Occurrences
                    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(sheet, text-block cell, None) for a note field, or (sheet or None, None, the code why not)."""
    sheet = resolve_sheet_name(note_field.sheet, cells)
    if sheet is None:
        return None, None, "no_sheet"
    rows = sorted({row for found_sheet, row, _ in occurrences.get(note_field.taxonomy_element_id or "", [])
                   if found_sheet == sheet})
    label_col = label_column(cells[sheet], rows[0]) if rows else None
    if label_col is None or not rows:
        return sheet, None, "no_note_cell"
    if len(rows) > 1:
        return sheet, None, "ambiguous"
    return sheet, f"{idx_to_col(col_to_idx(label_col) + 1)}{rows[0]}", None


def plan_notes(note_fields: list[NoteField], texts: dict[str, "Prepared"], cells: dict[str, Cells],
               occurrences: Occurrences) -> NotePlan:
    """The note writes, and the fields left out with their reason.
    `texts` holds the prepared text of each field that has notes placed."""
    plan = NotePlan()
    for note_field in note_fields:
        text = texts.get(note_field.field_id)
        if note_field.heading or text is None:
            continue
        entry = {"field_id": note_field.field_id, "field": note_field.label, "name": note_field.label,
                 "template": note_field.template_name, "revision": text.revision, "chars": text.chars,
                 "tier": text.tier, "cell": None}

        def out(where: list, code: str, cell: Optional[str] = None) -> None:
            where.append({**entry, "cell": cell, "code": code, "reason": NOTE_REASONS[code]})

        if text.too_long:
            out(plan.skipped, "too_long")
            continue
        sheet, trigger, problem = text_block_cell(note_field, cells, occurrences)
        if problem:
            out(plan.unresolved, problem)
            continue
        col, row = split_ref(trigger)
        if cells[sheet].get(row, {}).get(col, ("E", ""))[0] == "F":
            out(plan.skipped, "formula", f"{sheet}!{trigger}")
            continue
        plan.items.append({**entry, "cell": trigger, "sheet": sheet, "html": text.html})
    return plan

"""Where each field of a run sits in a genuine mTool workbook.

Shared by the scoring reader (`app/scoring/workbook_read.py`) and the mTool
fill (`app/filing/`), so a figure is written to the very cell it is read
from. Moved out of the step-2 reader unchanged.

A field is found only through its SSM name on its own sheet
(`mtool_address.find_cell`). A share-capital or related-party field without a
category of its own is placed once per category the taxonomy allows; its
Total column is the field with no category. Nothing is placed by position or
by label alone. A field that finds no cell, or more than one, is a miss with
its reason, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.catalog.dimensions import CATEGORY_SHEETS, dimension_key, numeric_category_catalog
from app.catalog.fields import FieldInfo
from app.catalog.lookup import RunFamily
from app.workbook import mtool_address, mtool_layout
from app.workbook.xlsx_cells import Cells, resolve_sheet_name

Key = tuple[str, str, str, str]      # concept_uuid, period, entity_scope, dimension_key
CellRef = tuple[str, int, str]       # the workbook's sheet, row, column


@dataclass
class Miss:
    reason: str                      # no_sheet | no_cell | ambiguous | columns_not_marked
    sheet: str | None                # the workbook's sheet, when found
    candidates: list[str] = field(default_factory=list)   # "Sheet!B12" for ambiguous and columns_not_marked


@dataclass
class FieldMap:
    claims: dict[CellRef, list[tuple[Key, FieldInfo]]] = field(default_factory=dict)  # two claims: a shared cell
    missed: dict[Key, tuple[Miss, FieldInfo]] = field(default_factory=dict)
    blocks: dict[str, list[dict]] = field(default_factory=dict)


def category_choices(info: FieldInfo, family: RunFamily, dimensional: bool) -> list[dict]:
    """A note field without its own category is placed once per category the
    taxonomy allows, when the sheet has category columns (v1 `_slot_writes`).
    The all-categories member is left out: its Total column is placed once,
    as the field with no category (`category_total_column`)."""
    axis_suffix = CATEGORY_SHEETS.get(info.sheet)
    if not (axis_suffix and dimensional and not info.dimensions):
        return [info.dimensions]
    aggregate = {m for ms in numeric_category_catalog(family.standard, roots_only=True).values() for m in ms}
    choices = [{axis: member} for axis, members in numeric_category_catalog(family.standard).items()
               if axis.endswith(axis_suffix) for member in members if member not in aggregate]
    return choices or [info.dimensions]


def map_fields(cells: dict[str, Cells], fields: dict[str, FieldInfo], family: RunFamily) -> FieldMap:
    """Place every field, entity and period of the run on the workbook. Both
    periods are placed; leaving out a prior year is the caller's decision."""
    occurrences = mtool_layout.index_taxonomy(cells)
    group = family.level == "group"
    out = FieldMap()
    layouts: dict[str, mtool_layout.SheetLayout | None] = {}
    totals: dict[tuple, tuple] = {}
    for info in fields.values():
        sheet = resolve_sheet_name(info.sheet, cells)
        if sheet is None:
            for entity in family.entity_scopes:
                for period in ("CY", "PY"):
                    out.missed[(info.concept_uuid, period, entity, "")] = (Miss("no_sheet", None), info)
            continue
        if sheet not in layouts:
            layouts[sheet] = mtool_layout.sheet_layout(cells[sheet], group=group)
            out.blocks[sheet] = mtool_layout.period_blocks(cells[sheet]) if layouts[sheet] and \
                layouts[sheet].dimensional else []
        layout = layouts[sheet]
        for dims in category_choices(info, family, bool(layout and layout.dimensional)):
            for entity in family.entity_scopes:
                for period in ("CY", "PY"):
                    key = (info.concept_uuid, period, entity, dimension_key(dims) if dims != info.dimensions
                           else "")
                    slot = mtool_address.Slot(info.concept_uuid, sheet, info.label, info.kind, info.primary,
                                              period, entity, dims)
                    hit = mtool_address.find_cell(slot, occurrences, layout, out.blocks[sheet], cells[sheet])
                    if hit.cell is None:
                        out.missed[key] = (Miss(hit.reason or "no_cell", sheet, hit.candidates), info)
                        continue
                    out.claims.setdefault(hit.cell, []).append((key, info))
                    if key[3] and info.sheet in CATEGORY_SHEETS:
                        totals.setdefault((info.concept_uuid, period, entity), (hit.cell, info))
    for (concept_uuid, period, entity), ((sheet, row, _), info) in totals.items():
        col = mtool_address.category_total_column(cells[sheet], out.blocks[sheet], row, period)
        if col is not None:
            key = (concept_uuid, period, entity, "")
            out.missed.pop(key, None)
            out.claims.setdefault((sheet, row, col), []).append((key, info))
    return out

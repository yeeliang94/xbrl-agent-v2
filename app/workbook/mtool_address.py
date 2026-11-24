"""Find the cell of one template field in a genuine mTool workbook, by its SSM name.

Copied from v1 `mtool/template_map.py` (`_resolve_taxonomy_target`,
`_dimension_column`, `_filter_candidates_for_period`, the exact-label tie
break in `resolve_filing_doc`) and v1 `eval/human_file.py`
(`_category_total_columns`, the Total column in `_slot_targets`).
Standard library only.

A field is found only through its SSM element name on the expected sheet,
then its column through the sheet's own period and entity markers, or, on a
category sheet, through its taxonomy category. A field that resolves to no
cell, or to more than one, is reported, never guessed. The operator choice
of a cell (v1's `filing_targets`) belongs to the fill and is not copied.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.workbook.mtool_layout import Occurrences, SheetLayout, block_for_row, category_domain_rows
from app.workbook.xlsx_cells import Cells

_BALANCE_ROLES = {"Equity at beginning of period": "periodStartLabel",
                  "Equity at end of period": "periodEndLabel"}


@dataclass(frozen=True)
class Slot:
    """One field, period and entity to find. `dimensions` are the category
    members that pick a category column (the equity component on the equity
    statement, a share class on the share-capital note)."""
    concept_uuid: str
    sheet: str              # the workbook's own sheet name
    label: str
    kind: str
    primary: str
    period: str
    entity_scope: str
    dimensions: dict = field(default_factory=dict, hash=False)


@dataclass
class Found:
    cell: tuple[str, int, str] | None = None     # (sheet, row, column)
    reason: str | None = None                    # "no_cell" | "ambiguous" | "columns_not_marked"
    candidates: list[str] = field(default_factory=list)


def _plain(text: str) -> str:
    return str(text or "").strip().lstrip("*").strip()


def _dimension_column(occurrences: Occurrences, dimensions: dict, *, sheet: str, block: dict | None,
                      period: str, entity_scope: str) -> str | None:
    """The one column on the sheet whose header carries every category member."""
    columns: set[str] | None = None
    for member in dimensions.values():
        found = set()
        for found_sheet, row, col in occurrences.get(member, []):
            if found_sheet != sheet:
                continue
            if block is not None:
                if block.get("entity_scopes") and block["entity_scopes"].get(col) != entity_scope:
                    continue
                if block.get("column_periods", {}).get(col) != period:
                    continue
                # Member headers sit above their #DOM# marker, after the previous block's.
                if row > block["dom_row"] or (block["previous_dom_row"] is not None
                                              and row <= block["previous_dom_row"]):
                    continue
            found.add(col)
        columns = found if columns is None else columns & found
    return next(iter(columns)) if columns and len(columns) == 1 else None


def _in_period(candidates: list[tuple[str, int, str]], slot: Slot, blocks: list[dict]) -> list:
    if not blocks:
        return candidates
    return [c for c in candidates if (block := block_for_row(blocks, c[1])) is not None
            and slot.period in block["periods"]
            and (not block.get("entity_scopes") or slot.entity_scope in block["entity_scopes"].values())]


def find_cell(slot: Slot, occurrences: Occurrences, layout: SheetLayout | None, blocks: list[dict],
              cells: Cells) -> Found:
    """The cell for one slot. Never a guess: no match or two matches are reported."""
    if layout is None or not slot.primary:
        return Found(reason="no_cell")
    candidates = [c for c in occurrences.get(slot.primary, []) if c[0] == slot.sheet]
    if layout.dimensional:
        if not slot.dimensions:
            return Found(reason="no_cell")
        candidates = _in_period(candidates, slot, blocks)
    balance_role = _BALANCE_ROLES.get(_plain(slot.label))
    if balance_role and slot.primary.endswith("_Equity"):
        kept = []
        for sheet, row, col in candidates:
            row_cells = cells.get(row, {})
            declared = re.search(r"/role/(periodStartLabel|periodEndLabel)", row_cells.get(col, (None, ""))[1] or "")
            if (declared and declared.group(1) == balance_role) or (
                    not declared and any(_plain(text) == _plain(slot.label) for _, text in row_cells.values())):
                kept.append((sheet, row, col))
        candidates = kept
    if slot.dimensions:
        candidates = [(s, r, col) for s, r, _ in candidates
                      if (col := _dimension_column(occurrences, slot.dimensions, sheet=s,
                                                   block=block_for_row(blocks, r), period=slot.period,
                                                   entity_scope=slot.entity_scope))]
    else:
        column = layout.columns.get((slot.entity_scope, slot.period))
        if candidates and not column:
            return Found(reason="columns_not_marked", candidates=[f"{s}!{col}{r}" for s, r, col in candidates])
        candidates = [(s, r, column) for s, r, _ in candidates] if column else []
    unique = list(dict.fromkeys(candidates))
    if len(unique) == 1:
        return Found(cell=unique[0])
    if not unique:
        return Found(reason="no_cell")
    # The SSM name, category and period already narrowed these. An exact row
    # label can tell repeated opening and closing rows apart; ties stay open.
    exact = [c for c in unique if _plain(cells.get(c[1], {}).get(layout.label_column, (None, ""))[1])
             == _plain(slot.label)]
    if len(exact) > 1 and slot.kind in ("LEAF", "MATRIX_CELL"):
        inputs = [c for c in exact if cells.get(c[1], {}).get(c[2], (None,))[0] != "F"]
        exact = inputs if len(inputs) == 1 else exact
    if len(exact) == 1:
        return Found(cell=exact[0])
    return Found(reason="ambiguous", candidates=[f"{s}!{col}{r}" for s, r, col in unique])


def category_total_column(cells: Cells, blocks: list[dict], row: int, period: str) -> str | None:
    """On a share-capital or related-party sheet, the Total column beside a
    category cell: the field's value with no category. None unless exactly one."""
    block = block_for_row(blocks, row)
    if block is None or block["dom_row"] not in category_domain_rows(cells):
        return None
    columns = [col for col, (_kind, text) in cells.get(block["dom_row"], {}).items()
               if (text or "").strip().lower() == "total" and block["column_periods"].get(col) == period]
    return columns[0] if len(columns) == 1 else None

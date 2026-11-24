"""From a run's figures to the cells of an mTool workbook: what to write, and
what not to, with the reason in plain words.

Rebuilt from v1 `mtool/exporter.py` (`build_fill_doc`) and the resolution in
`mtool/template_map.py` (`resolve_filing_doc`). The cells come from
`app/workbook/mtool_map.py`, the same placing the scoring reader reads
through, so a figure is written to the very cell scoring reads it from.

`plan_figures` is pure: it reads nothing and writes nothing. Each figure
lands in exactly one list:

- `writes`: one cell, an input cell, neither formula nor locked. A
  calculated total is never written, except the equity statement's
  across-the-row totals, which mTool leaves as input cells (as v1:
  `exporter.py`, `horizontal_input_total`; `row_totals` names them);
- `kept`: a calculated total the template works out with its own formula,
  left to that formula. A field whose SSM name sits on more than one row is
  kept too when it is a calculated total and one of those rows is the
  template's formula: v1 read such repeats to check them and wrote none
  (`resolve_filing_doc`, `verification_only`);
- `skipped`: a figure with no value (its cell stays empty, never zero), a
  prior-year figure on first financial statements, a prior-year figure on a
  note sheet that files the current year only (v1
  `_CURRENT_YEAR_ONLY_SHEETS`), an ordinary figure whose cells all hold a
  formula, a calculated total the template has no formula for, or a cell
  the template locks;
- `unresolved`: no cell, more than one input cell, a cell shared with
  another field, or a sheet the workbook does not have. Nothing is guessed.

Values pass through as stored: no scaling, no sign change.

`confirmed` is a mapping a person confirmed (step 12), from a figure's key
to a cell. It wins over the code's own cell for that figure, unless another
figure holds the cell; the same refusals (formula, locked) apply to it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.catalog.dimensions import CATEGORY_SHEETS
from app.catalog.fields import FieldInfo
from app.catalog.lookup import RunFamily
from app.workbook.mtool_map import CellRef, FieldMap, Key
from app.workbook.xlsx_cells import Cells

REASONS = {
    "written": "Written and read back.",
    "calculated": "The template adds this total up with its own formula, so it was left to the template.",
    "no_value": "No value in the source, so the cell is left empty.",
    "first_statements": "First financial statements have no prior year, so last year's figure was not written.",
    "formula": "The template works this line out with a formula, so it was not typed over.",
    "locked": "The template locks this cell, so it was not written.",
    "no_sheet": "The template has no sheet for this statement.",
    "no_cell": "The template has no cell for this field.",
    "ambiguous": "More than one cell in the template carries this field's name, so none was chosen.",
    "columns_not_marked": "The template does not mark which column is this year or last year, so none was chosen.",
    "shared_cell": "This field shares its cell with another field, so neither was written.",
    "not_a_field": "This figure is not a field of the run's templates.",
    "current_year_only": "This note files the current year only, so last year's figure stays in the run.",
    "total_not_written": "The app adds this total up and the template has no formula for it, so it was not typed in.",
    "read_back": "The filled file does not hold the value written, so check this cell.",
}


@dataclass
class FigurePlan:
    writes: list[dict] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)


def member_words(member: str) -> str:
    """`ifrs-full_OrdinarySharesMember` -> `Ordinary shares`."""
    name = member.split("_", 1)[-1]
    name = re.sub(r"Member$", "", name)
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).split()
    text = " ".join(w if w.isupper() else w.lower() for w in words)
    return text[:1].upper() + text[1:]


def figure_name(info: Optional[FieldInfo], key: Key, family: RunFamily, year: int, label: str = "") -> str:
    """The figure in words, as a receipt line names it: never a cell or an id.
    `label` names a figure that is not a field (from the catalogue)."""
    concept, period, entity, dims = key
    label = info.plain_label if info else (label.lstrip("*").strip() or "A figure not in the catalogue")
    parts = [label]
    members = [member_words(m) for m in json.loads(dims or "{}").values()]
    if info and info.matrix_col_label:   # the equity component the column is
        members.insert(0, info.matrix_col_label)
    category = ", ".join(members)
    if category:
        parts[0] = f"{label} ({category})"
    if family.level == "group":
        parts.append(entity)
    parts.append(str(year if period == "CY" else year - 1))
    return ", ".join(parts)


def _cell(ref: str) -> CellRef:
    sheet, addr = ref.rsplit("!", 1)
    col, row = re.fullmatch(r"([A-Z]+)(\d+)", addr).groups()
    return sheet, int(row), col


def _is_formula(cells: dict[str, Cells], cell: CellRef) -> bool:
    sheet, row, col = cell
    return cells.get(sheet, {}).get(row, {}).get(col, ("E", ""))[0] == "F"


def _ref(cell: CellRef) -> str:
    sheet, row, col = cell
    return f"{sheet}!{col}{row}"


def plan_figures(figures: list[dict], fields: dict[str, FieldInfo], placed: FieldMap, cells: dict[str, Cells],
                 family: RunFamily, *, year: int, locked: Callable[[str, str], bool],
                 row_totals: frozenset[str] = frozenset(), labels: Optional[dict[str, str]] = None,
                 confirmed: Optional[dict[Key, CellRef]] = None) -> FigurePlan:
    """The writes and the figures left out, each with its reason.

    `figures` are the run's current figures (`figures.store.run_figures`).
    `locked(sheet, cell)` says whether the template locks a cell.
    `row_totals` are the totals added up across their own row
    (`catalog.lookup.row_totals`). `labels` name, in words, figures that are
    not fields of the run's templates."""
    plan = FigurePlan()
    cell_of: dict[Key, CellRef] = {}
    shared: set[Key] = set()
    for cell, claims in placed.claims.items():
        for key, _info in claims:
            cell_of[key] = cell
            if len(claims) > 1:
                shared.add(key)
    taken: set[CellRef] = set()   # confirmed cells already given to a figure

    for figure in figures:
        key: Key = (figure["concept_uuid"], figure["period"], figure["entity_scope"], figure["dimension_key"])
        info = fields.get(key[0])
        entry = {"concept_uuid": key[0], "period": key[1], "entity_scope": key[2], "dimension_key": key[3],
                 "field": info.plain_label if info else "", "statement": info.statement if info else "",
                 "name": figure_name(info, key, family, year, (labels or {}).get(key[0], "")),
                 "value": figure["value"], "cell": None, "total": bool(info and info.is_total)}

        def out(where: list, code: str, cell: Optional[CellRef] = None) -> None:
            where.append({**entry, "cell": _ref(cell) if cell else None, "code": code, "reason": REASONS[code]})

        if figure["value"] is None:
            out(plan.skipped, "no_value")
            continue
        if key[1] == "PY" and family.first_statements:
            out(plan.skipped, "first_statements")
            continue
        if info is None:
            out(plan.unresolved, "not_a_field")
            continue
        if confirmed and key in confirmed:
            # A person chose this cell (step 12): it wins over the code's own choice, unless another figure
            # holds it.
            cell = tuple(confirmed[key])
            if any(other != key for other, _ in placed.claims.get(cell, [])) or cell in taken:
                out(plan.unresolved, "shared_cell", cell)
                continue
            taken.add(cell)
        elif key in shared:
            out(plan.unresolved, "shared_cell", cell_of.get(key))
            continue
        else:
            cell = cell_of.get(key)
        calculated = figure.get("origin") == "calculated"
        if cell is None:
            miss = placed.missed.get(key)
            if miss is None:
                out(plan.unresolved, "no_cell")
            elif miss[0].reason == "ambiguous" and (formulas := [c for c in map(_cell, miss[0].candidates)
                                                                 if _is_formula(cells, c)]):
                # Every repeat is the template's formula, or the figure is a total the template works out.
                if calculated:
                    out(plan.kept, "calculated", formulas[0])
                elif len(formulas) == len(miss[0].candidates):
                    out(plan.skipped, "formula", formulas[0])
                else:
                    out(plan.unresolved, "ambiguous")
            elif (miss[0].reason == "no_cell" and key[1] == "PY" and info.sheet in CATEGORY_SHEETS
                  and miss[0].sheet and placed.blocks.get(miss[0].sheet)
                  and not any("PY" in b["periods"] for b in placed.blocks[miss[0].sheet])):
                out(plan.skipped, "current_year_only")
            else:
                out(plan.unresolved, miss[0].reason)
            continue
        sheet, row, col = cell
        if _is_formula(cells, cell):
            out(plan.kept if calculated else plan.skipped, "calculated" if calculated else "formula", cell)
            continue
        if calculated and key[0] not in row_totals:
            out(plan.skipped, "total_not_written", cell)
            continue
        if locked(sheet, f"{col}{row}"):
            out(plan.skipped, "locked", cell)
            continue
        plan.writes.append({**entry, "cell": _ref(cell), "sheet": sheet, "address": f"{col}{row}"})
    return plan

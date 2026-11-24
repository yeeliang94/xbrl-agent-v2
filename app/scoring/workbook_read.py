"""Read the filled cells of a workbook a person filled, field by field.

Rebuilt from v1 `eval/human_file.py` (`read_human_file`, `_slot_writes`,
`_cell_number`, `_typed_rows`, `_slot_targets`). Two layouts are read:

- **mTool**: the workbook carries SSM field names. Each field is found by
  its name on its sheet (`app/workbook/mtool_map.py`, which the mTool fill
  also writes through).
- **template**: the app's own template layout (the files under
  `templates/`), with no SSM names. Each field is found at its template cell
  and trusted only when that row's label is the field's label (and, on the
  equity statement, the column header is the field's equity column).

Neither is ever read by position alone. Every cell is reported one of three
ways: read (a number, or blank), unread with a reason (`Unread`), or, for a
number no field claims, a loose cell. Nothing is dropped.

A total's cell is read only when a number was typed over the formula; a
formula there means "what the template calculates", worked out by the
comparison from the person's own lines, as v1 does. A formula typed into a
data-entry cell is worked out from the workbook's current values.
"""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from app.catalog.fields import FieldInfo, run_fields
from app.catalog.lookup import RunFamily, template_aliases, template_targets
from app.workbook import mtool_layout, mtool_map
from app.workbook.xlsx_cells import Cells, read_workbook, resolve_sheet_name, split_ref, taxonomy_ids
from app.workbook.xlsx_formulas import FormulaNotWorkedOut, WorkBudget, WorkBudgetSpent, calculated_value, \
    formula_cells

Key = tuple[str, str, str, str]   # concept_uuid, period, entity_scope, dimension_key
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
FORMULA_WORK = 1_000_000   # cells one read may visit working out formulas, across all of them


@dataclass
class PersonCell:
    value: Optional[float]    # None: blank, or a total left to its formula
    is_formula: bool          # the template's (or the person's) formula sits in a total's cell
    workbook_cell: str


@dataclass
class Unread:
    reason: str               # see api-contract.md, Step 2, NotAssessed
    sentence: str
    workbook_cell: Optional[str]
    holds_value: bool         # the workbook cell holds something


@dataclass
class WorkbookRead:
    layout: str                                           # "mtool" | "template"
    cells: dict[Key, PersonCell] = field(default_factory=dict)
    unread: dict[Key, Unread] = field(default_factory=dict)
    loose: list[dict] = field(default_factory=list)       # numbers no field claims


class NothingMatches(ValueError):
    """No field of the run's templates was found in the workbook."""


def cell_number(cell: Optional[tuple[str, str]]) -> Optional[float]:
    """A finite number, or numeric text (thousands commas, accounting brackets,
    a dash or nil for zero). Never a formula's cached result."""
    if not cell or cell[0] not in {"N", "S"}:
        return None
    raw = str(cell[1] or "").strip()
    if cell[0] == "S":
        if raw.casefold() in {"-", "–", "—", "nil"}:
            return 0.0
        if not re.fullmatch(rf"[+-]?(?:{_NUMBER})|\((?:{_NUMBER})\)", raw):
            return None
        raw = ("-" + raw[1:-1] if raw.startswith("(") else raw).replace(",", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class _Reader:
    def __init__(self, family: RunFamily, fields: dict[str, FieldInfo], data: dict, cells: dict[str, Cells]):
        self.family, self.fields, self.data, self.cells = family, fields, data, cells
        self.read = WorkbookRead("template")
        self.claimed: set[tuple[str, int, str]] = set()
        self._formulas: Optional[dict] = None
        self._cache: dict = {}
        self._budget = WorkBudget(FORMULA_WORK)

    def value_at(self, key: Key, info: FieldInfo, sheet: str, row: int, col: str) -> None:
        """Read one field's cell into `cells` or `unread`."""
        self.claimed.add((sheet, row, col))
        where = f"{sheet}!{col}{row}"
        cell = self.cells.get(sheet, {}).get(row, {}).get(col)
        holds = bool(cell and cell[0] != "E" and str(cell[1] or "").strip()) or bool(cell and cell[0] == "F")
        if key[1] == "PY" and self.family.first_statements:
            if holds:
                self.read.unread[key] = Unread("prior_year_first_statements", f"{where} holds a prior-year "
                                               "figure, which first financial statements do not have.", where, True)
            return
        if cell and cell[0] == "F":
            if info.is_total:
                self.read.cells[key] = PersonCell(None, True, where)
                return
            try:
                if self._formulas is None:
                    self._formulas = formula_cells(self.data)
                value = float(calculated_value(self._formulas, sheet, f"{col}{row}", cache=self._cache,
                                               budget=self._budget))
            except WorkBudgetSpent:
                self.read.unread[key] = Unread("formula_not_worked_out", f"{where} holds a formula that was not "
                                               "worked out, because the workbook's formulas need more work "
                                               "than one reading allows.", where, True)
                return
            except (FormulaNotWorkedOut, ValueError, ArithmeticError):
                self.read.unread[key] = Unread("formula_not_worked_out", f"{where} holds a formula that "
                                               "could not be worked out from the workbook.", where, True)
                return
            self.read.cells[key] = PersonCell(value, False, where)
            return
        value = cell_number(cell)
        if value is None and holds:
            self.read.unread[key] = Unread("not_a_number", f"{where} holds text, not a number.", where, True)
            return
        self.read.cells[key] = PersonCell(value, False, where)

    def keys(self, info: FieldInfo):
        for entity in self.family.entity_scopes:
            for period in ("CY", "PY"):
                yield (info.concept_uuid, period, entity, ""), entity, period

    # The app's own template layout ---------------------------------------

    def template_layout(self, conn: sqlite3.Connection) -> None:
        targets = template_targets(conn, set(self.fields))
        for concept_uuid, sheet, row, col in template_aliases(conn, set(self.fields)):
            self._alias(sheet, row, {t[2] for k, t in targets.items() if k[0] == concept_uuid} | {col})
        for info in self.fields.values():
            for key, entity, period in self.keys(info):
                target = targets.get((info.concept_uuid, entity, period))
                sheet = resolve_sheet_name(target[0], self.cells) if target else None
                if sheet is None:
                    continue
                _, row, col = target
                problem = self._label_problem(info, sheet, row, col)
                if problem:
                    self.claimed.add((sheet, row, col))
                    cell = self.cells[sheet].get(row, {}).get(col)
                    holds = bool(cell and (cell[0] == "F" or str(cell[1] or "").strip()))
                    self.read.unread[key] = Unread("label_mismatch", problem, f"{sheet}!{col}{row}", holds)
                    continue
                self.value_at(key, info, sheet, row, col)

    def _label_problem(self, info: FieldInfo, sheet: str, row: int, col: str) -> Optional[str]:
        label = str(self.cells[sheet].get(row, {}).get("A", ("", ""))[1] or "").strip()
        if label != info.label.strip():
            return f"{sheet} row {row} is labelled {label or 'nothing'!r}, not {info.label.strip()!r}."
        if info.matrix_col:
            header = str(self.cells[sheet].get(2, {}).get(col, ("", ""))[1] or "").strip()
            if info.matrix_col_label and header != info.matrix_col_label.strip():
                return f"{sheet} column {col} is headed {header or 'nothing'!r}, not {info.matrix_col_label!r}."
        return None

    def _alias(self, template_sheet: str, row: int, columns: set[str]) -> None:
        """A face line that repeats a sub-sheet total: claimed, never read."""
        sheet = resolve_sheet_name(template_sheet, self.cells)
        if sheet is None:
            return
        for col in columns:
            self.claimed.add((sheet, row, col))
            cell = self.cells[sheet].get(row, {}).get(col)
            if cell and cell[0] != "F" and cell_number(cell) is not None:
                self.read.loose.append({"reason": "repeats_a_total", "workbook_cell": f"{sheet}!{col}{row}",
                                        "sentence": f"{sheet}!{col}{row} holds a number on a line that "
                                                    "repeats a total from another sheet, so it was not read.",
                                        "sheet": template_sheet})

    # A genuine mTool workbook ---------------------------------------------

    def mtool_layout(self) -> None:
        self.read.layout = "mtool"
        placed = mtool_map.map_fields(self.cells, self.fields, self.family)
        for key, (miss, _info) in placed.missed.items():
            period, entity = key[1], key[2]
            if miss.reason == "ambiguous":
                self._claim(miss.candidates)
                self.read.unread[key] = Unread("ambiguous", f"{' and '.join(miss.candidates)} "
                                               "all carry this field's SSM name.", None,
                                               self._any_typed(miss.candidates))
            elif miss.reason == "columns_not_marked":
                # The numbers on the field's rows are listed here, not as loose cells.
                holds = self._claim_rows(miss.candidates)
                self.read.unread[key] = Unread("columns_not_marked", f"{miss.sheet} does not mark "
                                               f"which column is the {entity}, "
                                               f"{'this year' if period == 'CY' else 'last year'}.",
                                               None, holds)
        for (sheet, row, col), claims in placed.claims.items():
            if len(claims) == 1:
                self.value_at(claims[0][0], claims[0][1], sheet, row, col)
                continue
            self.claimed.add((sheet, row, col))
            for key, _info in claims:   # two fields cannot share one cell
                self.read.unread[key] = Unread("ambiguous", f"{sheet}!{col}{row} is the cell of more than one "
                                               "field.", f"{sheet}!{col}{row}", True)

    def _claim(self, refs: list[str]) -> None:
        """Cells already listed under an unmatched field, so they are not listed again as loose."""
        for ref in refs:
            sheet, addr = ref.rsplit("!", 1)
            col, row = split_ref(addr)
            self.claimed.add((sheet, row, col))

    def _claim_rows(self, refs: list[str]) -> bool:
        """Claim every number on the rows of `refs`. True when there is one."""
        found = False
        for ref in refs:
            sheet, addr = ref.rsplit("!", 1)
            row = split_ref(addr)[1]
            for col, cell in self.cells.get(sheet, {}).get(row, {}).items():
                if cell[0] == "F" or cell_number(cell) is not None:
                    self.claimed.add((sheet, row, col))
                    found = True
        return found

    def _any_typed(self, refs: list[str]) -> bool:
        for ref in refs:
            sheet, addr = ref.rsplit("!", 1)
            col, row = split_ref(addr)
            cell = self.cells.get(sheet, {}).get(row, {}).get(col)
            if cell and cell[0] in ("N", "S") and str(cell[1] or "").strip():
                return True
        return False

    # Numbers nobody claims ------------------------------------------------

    def loose_numbers(self) -> None:
        sheets = {s: t for t in {f.sheet for f in self.fields.values()}
                  if (s := resolve_sheet_name(t, self.cells))}
        for sheet, template_sheet in sheets.items():
            for row, row_cells in self.cells[sheet].items():
                texts = [str(raw or "") for kind, raw in row_cells.values() if kind == "S"]
                if any("::" in t and taxonomy_ids(t) or (t.strip().startswith("#") and t.strip().endswith("#"))
                       for t in texts):
                    continue   # an mTool header or marker row, not a figure
                for col, cell in row_cells.items():
                    if (sheet, row, col) in self.claimed or cell[0] == "F" or cell_number(cell) is None:
                        continue
                    label = next((str(r).strip() for k, r in row_cells.values()
                                  if k == "S" and str(r).strip() and not taxonomy_ids(r)), "")
                    self.read.loose.append({
                        "reason": "no_field", "workbook_cell": f"{sheet}!{col}{row}", "sheet": template_sheet,
                        "sentence": f"{sheet}!{col}{row}{f' ({label})' if label else ''} holds a number, but no "
                                    "field of the run's templates sits there."})


def read_filled_workbook(conn: sqlite3.Connection, family: RunFamily, path: str) -> WorkbookRead:
    """Read the workbook against the run's templates. Stores nothing.

    Raises `xlsx_cells.WorkbookUnreadable` or `NothingMatches`."""
    data, cells = read_workbook(path)
    fields = run_fields(conn, family)
    reader = _Reader(family, fields, data, cells)
    if mtool_layout.has_taxonomy_names(cells):
        reader.mtool_layout()
    else:
        reader.template_layout(conn)
    reader.loose_numbers()
    if not reader.read.cells and not reader.read.unread:
        raise NothingMatches("Nothing in this workbook matches the run's templates, so check that it was "
                             "filled for this run's statements.")
    return reader.read

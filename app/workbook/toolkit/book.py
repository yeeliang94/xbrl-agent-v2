"""One workbook, read once for the toolkit's scripts: its cells, its layout marks and which cells it locks."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from app.workbook import offline_fill
from app.workbook.mtool_layout import sheet_layout
from app.workbook.xlsx_cells import TAXONOMY_HREF, Cells, col_to_idx, read_workbook, sheet_paths

REF = re.compile(r"^(?P<sheet>.+)!(?P<col>[A-Z]{1,3})(?P<row>[1-9]\d*)$")
_MARK = re.compile(r"^#[A-Z]+#$")


class NotFound(ValueError):
    """A sheet or cell the workbook does not have. `str()` is one plain sentence."""


@dataclass
class Book:
    path: Path
    group: bool = False   # a Group filing: its sheets mark Group and Company columns

    def __post_init__(self):
        self.path = Path(self.path)

    @cached_property
    def _read(self):
        return read_workbook(str(self.path))

    @property
    def data(self) -> dict[str, bytes]:
        return self._read[0]

    @property
    def cells(self) -> dict[str, Cells]:
        return self._read[1]

    @cached_property
    def members(self) -> dict[str, str]:
        return sheet_paths(self.data)

    @cached_property
    def _protection(self) -> dict:
        return offline_fill.protected_input_cells(self.data, self.members)

    def locked(self, sheet: str, addr: str) -> bool:
        return offline_fill.is_locked_input(self._protection, sheet, addr)

    def sheet(self, name: str) -> Cells:
        if name in self.cells:
            return self.cells[name]
        found = [s for s in self.cells if s.casefold() == name.casefold()]
        if len(found) == 1:
            return self.cells[found[0]]
        raise NotFound(f"The workbook has no sheet named {name}; list_rows with no sheet lists them.")

    def sheet_name(self, name: str) -> str:
        self.sheet(name)
        return name if name in self.cells else next(s for s in self.cells if s.casefold() == name.casefold())

    def layout(self, name: str):
        return sheet_layout(self.sheet(name), group=self.group)


def parse_ref(ref: str) -> tuple[str, int, str]:
    """`Sheet!C12` as (sheet, 12, "C"). Raises NotFound with one sentence."""
    match = REF.match(ref.strip())
    if match is None:
        raise NotFound(f"{ref!r} is not a cell; write it as Sheet!C12.")
    return match["sheet"], int(match["row"]), match["col"]


def ssm_names(text: str) -> list[str]:
    return TAXONOMY_HREF.findall(text or "")


def is_mark(text: str) -> bool:
    return bool(_MARK.match((text or "").strip()))


def row_label(sheet_cells: Cells, row: int) -> str:
    """The row's own words: its first text cell that is neither a layout mark nor an SSM name."""
    cells = sheet_cells.get(row, {})
    for col in sorted(cells, key=col_to_idx):
        kind, text = cells[col]
        if kind == "S" and text.strip() and not is_mark(text) and not ssm_names(text):
            return " ".join(text.split()).lstrip("*").strip()
    return ""


def describe(book: Book, sheet: str, row: int, col: str) -> str:
    """What one cell holds, in words: `number 1200`, `text "..."`, `formula`, `empty`; and `locked`."""
    kind, text = book.sheet(sheet).get(row, {}).get(col, ("", ""))
    what = {"F": f"formula showing {text.strip()[:30]}" if (text or "").strip() else "formula", "N": f"number {text}", "S": f"text {text[:60]!r}", "E": "empty", "": "empty"}[kind]
    return what + (", locked" if book.locked(book.sheet_name(sheet), f"{col}{row}") else "")

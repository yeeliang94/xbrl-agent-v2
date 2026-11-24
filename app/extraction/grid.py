"""The equity statement as a grid: rows are movements in equity, columns are
components of equity, and every cell is a field with its own id
`CE-<row>-<column>` (for example `CE-11-C`, profit in the retained earnings
column).

Why (step 7 plan, 7a): the outline listed one field per row, the last column,
so the agent saw only the total column and could not reach the component
columns. Here the columns are listed once (letter, label, and which columns
are totals of which), the rows once (label, line or total, and what a total
row adds up), worked out from the template's own formulas, so the view holds
for any equity template (MFRS, MPERS, Company or Group). A cell that does not
follow its row and column is listed on its own.

The cell ids are the outline's own and never change; a row (`CE-11`) and a
column (`CE-C`) are names for `show_section` and `find_fields` only. The
text the agent reads is `outline_text.render_grid` and `grid_section`.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Union

from app.extraction.outline import HEADING, LINE, TOTAL, Outline

Parts = tuple[tuple[str, float], ...]   # (row number or column letter as text, coefficient)


@dataclass
class Column:
    letter: str
    label: str
    parts: Parts = ()          # a total column: the columns it adds up, each with its sign

    @property
    def kind(self) -> str:
        return TOTAL if self.parts else LINE


@dataclass
class Row:
    row: int
    label: str
    heading: bool = False
    mandatory: bool = False
    path: tuple[str, ...] = ()
    parts: Parts = ()          # a total row: the rows it adds up, each with its sign

    @property
    def kind(self) -> str:
        return HEADING if self.heading else TOTAL if self.parts else LINE


@dataclass
class Grid:
    statement: str
    code: str
    columns: list[Column] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)                  # in template order, headings included
    cells: dict[tuple[int, str], str] = field(default_factory=dict)   # (row, column letter) -> field id
    odd: list[str] = field(default_factory=list)       # ids of cells that follow neither their row nor column
    missing: list[tuple[int, str]] = field(default_factory=list)   # (row, column) with no cell

    def row_id(self, row: int) -> str:
        return f"{self.code}-{row}"

    def column_id(self, letter: str) -> str:
        return f"{self.code}-{letter}"

    def column(self, letter: str) -> Optional[Column]:
        return next((c for c in self.columns if c.letter == letter), None)

    def find(self, name: str) -> Optional[Union[Row, Column]]:
        """The row or the column a name such as CE-11 or CE-C stands for, ignoring case and spaces."""
        key = "".join(str(name).split()).upper()
        code, dash, rest = key.partition("-")
        if not dash or code != self.code.upper() or "-" in rest:
            return None
        if rest.isdigit():
            return next((r for r in self.rows if r.row == int(rest) and not r.heading), None)
        return self.column(rest)

    def example(self, item: Union[Row, Column, None] = None) -> Optional[str]:
        """A line cell's id, in the row or column given when there is one, for a message to the agent."""
        rows = [item] if isinstance(item, Row) else [r for r in self.rows if not r.heading and not r.parts]
        cols = [item] if isinstance(item, Column) else [c for c in self.columns if not c.parts]
        return next((self.cells[(r.row, c.letter)] for r in rows for c in cols if (r.row, c.letter) in self.cells),
                    None)


def _letter(fid: str) -> str:
    return fid.rsplit("-", 1)[1]


def _common(found: list[Parts]) -> Parts:
    return Counter(found).most_common(1)[0][0] if found else ()


def build(outline: Outline, statement: str) -> Optional[Grid]:
    """The grid of one statement, or None when the statement is not a grid."""
    cells = [f for f in outline.fields.values() if f.statement == statement and f.column_label]
    if not cells:
        return None
    code = cells[0].id.split("-", 1)[0]
    grid = Grid(statement, code)
    by_cell = {(f.row, _letter(f.id)): f for f in cells}
    grid.cells = {key: f.id for key, f in by_cell.items()}
    place = {f.id: (f.row, _letter(f.id)) for f in cells}
    letters = sorted({c for _, c in by_cell}, key=lambda c: (len(c), c))
    row_numbers = sorted({r for r, _ in by_cell})

    def same_row(f) -> Optional[Parts]:
        spots = [place.get(p) for p, _ in f.parts]
        if f.kind != TOTAL or not spots or any(s is None or s[0] != f.row for s in spots):
            return None
        return tuple(sorted(((s[1], k) for s, (_, k) in zip(spots, f.parts)), key=lambda p: (len(p[0]), p[0])))

    def same_column(f) -> Optional[Parts]:
        spots = [place.get(p) for p, _ in f.parts]
        if f.kind != TOTAL or not spots or any(s is None or s[1] != _letter(f.id) for s in spots):
            return None
        return tuple(sorted(((str(s[0]), k) for s, (_, k) in zip(spots, f.parts)), key=lambda p: int(p[0])))

    for letter in letters:
        found = [p for r in row_numbers if (f := by_cell.get((r, letter))) and (p := same_row(f))]
        label = next(f.column_label for (r, c), f in sorted(by_cell.items()) if c == letter)
        grid.columns.append(Column(letter, label, _common(found)))
    rows: dict[int, Row] = {}
    for r in row_numbers:
        here = [f for (row, _), f in by_cell.items() if row == r]
        found = [p for f in here if (p := same_column(f))]
        rows[r] = Row(r, here[0].label, mandatory=any(f.mandatory for f in here), path=here[0].path,
                      parts=_common(found))
    for f in outline.fields.values():
        if f.statement == statement and f.kind == HEADING and not f.column_label and f.row not in rows:
            rows[f.row] = Row(f.row, f.label, heading=True)
    grid.rows = [rows[r] for r in sorted(rows)]

    for r in row_numbers:   # a cell is a total when its row or its column is one; list any that is not
        row = rows[r]
        for col in grid.columns:
            f = by_cell.get((r, col.letter))
            if f is None:
                grid.missing.append((r, col.letter))
                continue
            expected = TOTAL if (row.parts or col.parts) else LINE
            own = same_row(f) if col.parts else same_column(f) if row.parts else None
            wanted = col.parts if col.parts else row.parts
            if f.kind != expected or (expected == TOTAL and own != wanted):
                grid.odd.append(f.id)
    return grid


def names(grid: Grid) -> dict[str, str]:
    """Each row id as a person names it, so text an agent writes reads by label (`Outline.readable`)."""
    return {grid.row_id(r.row).upper(): r.label for r in grid.rows if not r.heading}

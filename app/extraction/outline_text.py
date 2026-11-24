"""The outline as text: the compact view in the figures agent's first message,
and the detailed view of one section that `show_section` returns."""
from __future__ import annotations

from typing import Mapping, Optional

from app.extraction.grid import Column, Grid, Parts, Row
from app.extraction.outline import HEADING, TOTAL, Field, Outline
from app.figures.sums import fmt_amount

LEGEND = """\
How to read the outline. Every field has its own id: save and clear figures by id, never by label.
- "heading": a section title. It never holds a value.
- "line": a field to fill.
- "total": the template works it out from the parts named after "=", each with its sign. Do not type \
it: save its parts. You may also record the amount the report prints for a total, saved as printed, so the \
checks compare the two.
- A total marked "face row" is a formula on the face statement fed by the sub-sheet lines nested under \
it: fill those lines and the face row follows.
- Nesting shows which total each line belongs to. * marks a field the filing requires."""


def _parts(f: Field) -> str:
    out = []
    for i, (part, coefficient) in enumerate(f.parts):
        sign = "-" if coefficient < 0 else "+"
        scale = "" if abs(abs(coefficient) - 1) < 1e-9 else f"{abs(coefficient):g}x"
        out.append(f"{'' if i == 0 and sign == '+' else sign + ' '}{scale}{part}")
    return " ".join(out)


def line_of(f: Field) -> str:
    star = "*" if f.mandatory else ""
    if f.kind == HEADING:
        return f"{f.id} heading: {f.label}"
    if f.kind == TOTAL:
        face = " (face row)" if f.face_label else ""
        return f"{f.id} total{face}: {star}{f.name} = {_parts(f) or 'nothing yet'}"
    return f"{f.id} line: {star}{f.label}"


def _tree(outline: Outline, fid: str, depth: int, out: list[str]) -> None:
    out.append("  " * depth + line_of(outline.fields[fid]))
    for child in outline.fields[fid].children:
        _tree(outline, child, depth + 1, out)


def render(outline: Outline, statement: str) -> str:
    """The whole statement's outline, compact enough for the first message. The equity statement is shown
    as its grid of rows and columns (`grid.py`)."""
    if statement in outline.grids:
        return render_grid(outline, outline.grids[statement], outline.titles.get(statement, statement))
    out = [f"Template outline: {outline.titles.get(statement, statement)}", LEGEND, ""]
    for fid in outline.roots.get(statement, []):
        f = outline.fields[fid]
        if f.kind == HEADING:
            out.append(line_of(f))
        else:
            _tree(outline, fid, 1, out)
    loose = outline.loose.get(statement, [])
    if loose:
        out += ["", "Sub-sheet breakdowns that no face row adds up. The face line for the same item is typed "
                    "directly; fill these as well only when a note gives the breakdown:"]
        for fid in loose:
            _tree(outline, fid, 1, out)
    return "\n".join(out)


Values = Mapping[tuple[str, str], tuple[Optional[float], Optional[float]]]   # (uuid, period) -> (value, printed)


def saved_text(f: Field, values: Values, periods: tuple[str, ...]) -> str:
    shown = []
    for period in periods:
        value, printed = values.get((f.concept_uuid, period), (None, None))
        text = "blank" if value is None else fmt_amount(value)
        if printed is not None:
            text += f" (printed {fmt_amount(printed)})"
        shown.append(f"{period} {text}")
    return ", ".join(shown)


def section(outline: Outline, fid: str, values: Values, periods: tuple[str, ...]) -> str:
    """One field and everything nested under it, with paths, parts and what is saved now."""
    f = outline.fields[fid]
    out = [f"{f.id} is a {f.kind}: {f.where}"]
    if f.kind != HEADING:
        out.append(f"Saved now: {saved_text(f, values, periods)}.")
    if f.used_by:
        out.append("Added into: " + ", ".join(f"{u} {outline.fields[u].name}" for u in f.used_by) + ".")
    if f.kind == TOTAL:
        out.append("Parts:")
        for part, coefficient in f.parts:
            p = outline.fields[part]
            sign = "minus" if coefficient < 0 else "plus"
            out.append(f"  {sign} {p.id} {p.kind}: {p.name}; saved {saved_text(p, values, periods)}")
    below = outline.descendants(fid)
    if below:
        out.append("Nested under it:")
        for child in below:
            c = outline.fields[child]
            depth = len(c.path) - len(f.path)
            saved = "" if c.kind == HEADING else f"; saved {saved_text(c, values, periods)}"
            out.append("  " * max(depth, 1) + line_of(c) + saved)
    return "\n".join(out)


# The equity grid (`grid.py`) ----------------------------------------------------

def _formula(parts: Parts, name) -> str:
    out = []
    for i, (part, coefficient) in enumerate(parts):
        sign = "-" if coefficient < 0 else "+"
        scale = "" if abs(abs(coefficient) - 1) < 1e-9 else f"{abs(coefficient):g}x"
        out.append(f"{'' if i == 0 and sign == '+' else sign + ' '}{scale}{name(part)}")
    return " ".join(out)


def render_grid(outline: Outline, grid: Grid, title: str) -> str:
    """The grid for the first message: the columns once, the rows once, and how a cell is named."""
    first = next((r for r in grid.rows if not r.heading and not r.parts), None)
    line_col = next((c for c in grid.columns if not c.parts), None)
    cell = grid.example()
    example = (f" For example {cell} is {outline.fields[cell].label} in the {outline.fields[cell].column_label} "
               "column." if cell else "")
    out = [
        f"Template outline: {title}",
        "How to read the outline. This statement is a grid: each row is a movement in equity, each column a "
        f"component of equity. A cell's id is {grid.code}-<row>-<column>.{example} Save and clear figures by cell "
        "id, never by label.",
        "- A \"line\" row or column holds figures to fill. A \"total\" row or column is worked out by the "
        "template from the rows or columns named after \"=\", each with its sign; a cell is a total when its row "
        "or its column is one. Do not type a total: save the line cells. You may also record the amount the "
        "report prints for a total cell, saved as printed, so the checks compare the two.",
        f"- show_section takes a cell id, a row ({grid.row_id(first.row) if first else grid.code + '-<row>'}) or a "
        f"column ({grid.column_id(line_col.letter) if line_col else grid.code + '-<column>'}) and shows its cells "
        "with what is saved; find_fields finds rows, columns and cells by label.",
        "- * marks a row the filing requires.",
        "",
        "Columns:",
    ]
    for col in grid.columns:
        out.append(f"- {col.letter} {col.label}: " + (f"total = {_formula(col.parts, str)}" if col.parts
                                                       else "line"))
    out += ["", "Rows:"]
    for row in grid.rows:
        if row.heading:
            out.append(f"{grid.row_id(row.row)} heading: {row.label}")
            continue
        star = "*" if row.mandatory else ""
        formula = _formula(row.parts, lambda r: grid.row_id(int(r)))
        out.append(f"  {grid.row_id(row.row)} {star}{row.label}: " + (f"total = {formula}" if row.parts
                                                                      else "line"))
    if grid.odd or grid.missing:
        out += ["", "Cells that do not follow their row and column:",
                *[f"- {line_of(outline.fields[fid])}" for fid in grid.odd],
                *[f"- {grid.row_id(r)} has no cell in column {c}." for r, c in grid.missing]]
    return "\n".join(out)


def grid_section(outline: Outline, grid: Grid, name: str, values: Values, periods: tuple[str, ...]
                 ) -> Optional[str]:
    """A row's or a column's cells with what is saved in each, or None when `name` is neither."""
    item = grid.find(name)
    if isinstance(item, Row):
        head = (f"{grid.row_id(item.row)} is a {item.kind} row of the grid: {' › '.join(item.path + (item.label,))}"
                + (f" = {_formula(item.parts, lambda r: grid.row_id(int(r)))}" if item.parts else "") + ".")
        cells = [((item.row, c.letter), c.label) for c in grid.columns]
    elif isinstance(item, Column):
        head = (f"{grid.column_id(item.letter)} is a {item.kind} column of the grid: {item.label}"
                + (f" = {_formula(item.parts, str)}" if item.parts else "") + ".")
        cells = [((r.row, item.letter), r.label) for r in grid.rows if not r.heading]
    else:
        return None
    out = [head, "Cells:"]
    for key, label in cells:
        fid = grid.cells.get(key)
        if fid is not None:
            f = outline.fields[fid]
            out.append(f"  {fid} {f.kind}: {label}; saved {saved_text(f, values, periods)}")
    return "\n".join(out)

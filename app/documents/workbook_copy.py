"""An Excel workbook (.xlsx) as a reading copy and its own lines.

`openpyxl` reads the workbook; Excel itself is never run. Each sheet is laid
out from the top of a new page as a grid with its column letters and row
numbers, so a person and an agent name a cell the same way. A formula is
read by the result Excel saved with it; one saved without a result reads as
empty, is marked so, and is counted, so the person can be told. Hidden
sheets are left out unless the person brings them in, and are then laid out
after the others, so the pages already read keep their numbers.
"""
from __future__ import annotations

import io
import math
import re
import zipfile
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, localcontext
from html import escape
from typing import Any, Sequence

import openpyxl
from lxml import etree
from openpyxl.utils import get_column_letter, range_boundaries

from app.documents import reading_copy as rc
from app.documents.source_file import EXCEL, Refused, unreadable

# A workbook with more filled cells than this is no set of statements, and laying it out would take minutes.
MAX_CELLS = 200_000
# Each sheet is drawn as a grid of its used rows by its used columns, empty places included, so a few
# cells far apart would draw millions. This bounds the grid across the workbook.
MAX_GRID = 1_000_000
NO_RESULT = "[no saved result]"
# A Word or Excel file is a zip; its parts unpacked may be far larger than the upload.
MAX_UNZIPPED = 300 * 1024 * 1024


def _pick(number_format: str, value: float | int) -> tuple[str, bool]:
    """The format section Excel uses for this value, and whether that section writes the sign itself.
    A format has up to four sections, `positive;negative;zero;text`: a negative takes the second when
    there is one, and a zero the third."""
    sections = number_format.split(";")
    if value < 0 and len(sections) > 1:
        return sections[1], True
    if value == 0 and len(sections) > 2:
        return sections[2], True
    return sections[0], False


def _section(section: str) -> str:
    """A format section without its quoted text and padding (`_)`), which hold no digits."""
    return re.sub(r'"[^"]*"|\\.|_.', "", section)


def _decimals(section: str) -> int | None:
    """The decimal places a format section shows, or None for General."""
    section = _section(section)
    if "0" not in section and "#" not in section:
        return None
    if "." not in section:
        return 0
    return len(re.match(r"[0#]*", section.split(".", 1)[1]).group(0))


def _scale(section: str) -> int:
    """How many times a format section divides by a thousand: a comma after the last digit, as in
    `#,##0,` (thousands) or `0.0,,` (millions)."""
    found = re.search(r"[0#](,+)[^0#]*$", _section(section))
    return len(found.group(1)) if found else 0


def _rounded(value: float | int, scale_by: Decimal, decimals: int) -> Decimal | None:
    """The value's size rounded as Excel rounds, a half away from zero (1,284,500 in thousands shows
    1,285; Python's own formatting rounds it to even). None for a value that is not a finite number."""
    exact = Decimal(str(value)) * scale_by
    if not exact.is_finite():
        return None
    with localcontext() as context:
        context.prec = max(28, exact.adjusted() + decimals + 4)     # a huge amount keeps every digit
        return abs(exact).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def shown(value: Any, number_format: str = "General") -> str:
    """A cell's value as its sheet shows it, near enough to read: thousands separators, decimal
    places, brackets for a negative and a percent sign follow the cell's number format."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return f"{value.day} {value:%B %Y}"
    if isinstance(value, date):
        return f"{value.day} {value:%B %Y}"
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (int, float)):
        section, signed = _pick(number_format or "General", value)
        percent = "%" in _section(section)
        scale_by = Decimal(100) if percent else Decimal(1000) ** -_scale(section)
        decimals = _decimals(section)
        rounded = None if decimals is None else _rounded(value, scale_by, decimals)
        if rounded is None:
            return plain(value * float(scale_by)) + ("%" if percent else "")
        grouped = re.search(r"[0#],[0#]", _section(section)) is not None
        body = f"{rounded:,.{decimals}f}" if grouped else f"{rounded:.{decimals}f}"
        if signed:                   # the section writes the sign itself, as brackets or a minus
            mark = _section(section)
            body = f"({body})" if "(" in mark else f"-{body}" if "-" in mark else body
        elif value < 0 and rounded != 0:
            body = f"-{body}"
        return body + ("%" if percent else "")
    return " ".join(str(value).split())


def plain(number: float | int) -> str:
    """A number in full, with no separators: 1284300, -0.125."""
    if not math.isfinite(number):
        return str(number)
    if isinstance(number, int) or (number == int(number) and abs(number) < 1e15):
        return str(int(number))
    return f"{number:.10f}".rstrip("0").rstrip(".")


def _saved(value: Any) -> float | int | None:
    """The number a cell holds, for a cell that holds one."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _stored(sheet) -> list:
    """The cells the file stores, in row order. Not `iter_rows`, which makes a cell for every position up
    to the last one used, so two cells far apart would make millions."""
    return sorted(sheet._cells.values(), key=lambda c: (c.row, c.column))   # noqa: SLF001 - openpyxl 3.1.5


def _by_row(cells: list) -> list[list]:
    rows: list[list] = []
    for cell in cells:
        if rows and rows[-1][0].row == cell.row:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    return rows


def _sheet_rows(values, formulas) -> tuple[list[tuple[int, list]], list[str], int]:
    """(rows as (row number, cells), the column letters used, formulas saved without a result)."""
    rows, used, empty = [], set(), 0
    formula_cells = {(c.row, c.column) for c in _stored(formulas) if getattr(c, "data_type", "") == "f"}
    for row in _by_row(_stored(values)):
        cells = []
        for cell in row:
            no_result = cell.value is None and (cell.row, cell.column) in formula_cells
            text = NO_RESULT if no_result else shown(cell.value, getattr(cell, "number_format", "General"))
            if not text:
                continue
            empty += no_result
            letter = get_column_letter(cell.column)
            used.add(cell.column)
            cells.append([letter, text, _saved(cell.value)])
        if cells:
            rows.append((row[0].row, cells))
    return rows, [get_column_letter(c) for c in sorted(used)], empty


def _part(name: str, rows: list[tuple[int, list]], columns: list[str]) -> rc.Part:
    lines: dict[str, rc.Line] = {}
    size = 9 if len(columns) <= 8 else 7 if len(columns) <= 14 else 6
    out = [f"<h2>{escape(name)}</h2>", f'<table style="font-size:{size}pt"><tr><th class="ref"></th>',
           "".join(f'<th class="col">{c}</th>' for c in columns), "</tr>"]
    for number, cells in rows:
        key = f"r{number}"
        lines[key] = rc.Line(rc.ROW, cells, sheet=name, row=number)
        by_column = {letter: text for letter, text, _ in cells}
        out.append(f'<tr id="{key}"><td class="ref">{number}</td>'
                   + "".join(rc.cell_html(by_column.get(c, "")) for c in columns) + "</tr>")
    out.append("</table>")
    return rc.Part(html="".join(out), lines=lines, wide=len(columns) > rc.WIDE_FROM_COLUMNS)


def unzipped_too_large(filename: str, data: bytes) -> None:
    """Refuse a Word or Excel file that unpacks to more than `MAX_UNZIPPED` bytes, before it is parsed:
    a small file can hold a huge one."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            size = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        return                       # the reader refuses it in its own words
    if size > MAX_UNZIPPED:
        raise Refused(f"{filename} unpacks to more than {MAX_UNZIPPED // (1024 * 1024)} MB, so upload the "
                      "financial statements on their own.")


def merged_too_large(filename: str, data: bytes) -> None:
    """Refuse a workbook whose merged ranges cover more than `MAX_CELLS` cells, before it is loaded:
    openpyxl makes one cell for every merged position, so a small file could fill the memory."""
    covered = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if not info.filename.startswith("xl/worksheets/"):
                    continue
                # Read as XML, as openpyxl will, so no spelling of the attribute slips past.
                with archive.open(info) as stream:
                    for _, merge in etree.iterparse(stream, tag="{*}mergeCell", resolve_entities=False,
                                                    no_network=True, huge_tree=False):
                        first_col, first_row, last_col, last_row = range_boundaries(merge.get("ref") or "")
                        covered += (last_col - first_col + 1) * (last_row - first_row + 1)
                        merge.clear()
                        if covered > MAX_CELLS:
                            break
    except (zipfile.BadZipFile, ValueError, TypeError, etree.XMLSyntaxError):
        return                       # the reader refuses it in its own words
    if covered > MAX_CELLS:
        raise Refused(f"{filename} has merged cells covering more than {MAX_CELLS:,} cells, so upload the "
                      "financial statements on their own.")


def workbook_copy(filename: str, data: bytes, brought_in: Sequence[str] = ()) -> tuple[rc.ReadingCopy, list[dict]]:
    """The reading copy of an .xlsx file and its sheets, or Refused. `brought_in` names the hidden
    sheets a person brought in, in the order they did. Each sheet: name, hidden, used (laid out),
    first_page, last_page, rows and empty_formulas."""
    unzipped_too_large(filename, data)
    merged_too_large(filename, data)
    try:
        values = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        formulas = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises several types for a broken file
        raise unreadable(filename, EXCEL) from exc
    sheets, parts, order = [], {}, []
    total = grid = 0
    for sheet in values.worksheets:
        hidden = sheet.sheet_state != "visible"
        wanted = not hidden or sheet.title in brought_in
        info = {"name": sheet.title, "hidden": hidden, "used": False, "first_page": None, "last_page": None,
                "rows": 0, "empty_formulas": 0}
        sheets.append(info)
        if not wanted:
            continue
        rows, columns, empty = _sheet_rows(sheet, formulas[sheet.title])
        total += sum(len(cells) for _, cells in rows)
        if total > MAX_CELLS:
            raise Refused(f"{filename} holds more than {MAX_CELLS:,} filled cells, so upload the financial "
                          "statements on their own.")
        grid += len(rows) * len(columns)
        if grid > MAX_GRID:
            raise Refused(f"{filename} spreads its cells over more than {MAX_GRID:,} places, so upload the "
                          "financial statements on their own.")
        info.update(rows=len(rows), empty_formulas=empty)
        if rows:
            parts[sheet.title] = _part(sheet.title, rows, columns)
            order.append(sheet.title)
    # Sheets a person brought in go last, in the order they brought them in.
    order.sort(key=lambda name: list(brought_in).index(name) + 1 if name in brought_in else 0)
    if not order:
        raise Refused(f"{filename} has no sheet with anything on it to read.")
    copy = rc.lay_out([parts[name] for name in order])
    by_name = {s["name"]: s for s in sheets}
    for name, (first, last) in zip(order, copy.part_pages):
        by_name[name].update(used=True, first_page=first, last_page=last)
    return copy, sheets

"""The sheets of a workbook, or one sheet's rows: its label, its SSM name and each value cell.

    venv/bin/python -m app.workbook.toolkit.list_rows book.xlsx
    venv/bin/python -m app.workbook.toolkit.list_rows book.xlsx SOFP-CuNonCu --start 1 --rows 60
"""
from __future__ import annotations

import argparse

from app.workbook.toolkit.book import Book, describe, is_mark, ssm_names
from app.workbook.xlsx_cells import col_to_idx

MAX_ROWS = 80


def sheet_line(book: Book, name: str) -> str:
    cells = book.cells[name]
    layout = book.layout(name)
    if layout is None:
        marks = "no layout marks"
    else:
        columns = ", ".join(f"{col} {entity} {'this year' if period == 'CY' else 'last year'}"
                            for (entity, period), col in sorted(layout.columns.items(), key=lambda x: x[1]))
        marks = (f"label column {layout.label_column}" + (f"; value columns {columns}" if columns else "")
                 + ("; one block of columns per category" if layout.dimensional else ""))
    named = sum(1 for row in cells.values() for _, text in row.values() if ssm_names(text))
    return f"{name}: {len(cells)} rows, {named} SSM names, {marks}"


def row_line(book: Book, sheet: str, row: int) -> str:
    """`r12 | Trade and other receivables | SSM ...TradeAndOtherReceivables | C: empty, D: number 1200`."""
    cells = book.sheet(sheet).get(row, {})
    words, names, values = [], [], []
    for col in sorted(cells, key=col_to_idx):
        kind, text = cells[col]
        if kind == "S" and text.strip() and not is_mark(text):
            found = ssm_names(text)
            (names.extend(found) if found else words.append(f"{col}: {text.strip()[:80]}"))
        elif is_mark(text):
            values.append(f"{col}: {text.strip()}")
        elif kind in ("N", "E", "F"):
            said = describe(book, sheet, row, col)
            if said != "empty, locked":   # an empty cell nobody can type in says nothing
                values.append(f"{col}: {said}")
    parts = [f"r{row}", " ; ".join(words) or "-"]
    if names:
        parts.append("SSM " + ", ".join(names))
    if values:
        parts.append(", ".join(values))
    return " | ".join(parts)


def run(book: Book, sheet: str | None = None, start: int = 1, rows: int = 60) -> str:
    if sheet is None:
        return "\n".join(sheet_line(book, name) for name in book.cells)
    name = book.sheet_name(sheet)
    numbers = [r for r in sorted(book.cells[name]) if r >= start][:max(1, min(rows, MAX_ROWS))]
    out = [row_line(book, name, r) for r in numbers if book.cells[name][r]]
    last = max(book.cells[name], default=0)
    if numbers and numbers[-1] < last:
        out.append(f"More rows follow, to r{last}: list_rows again with start {numbers[-1] + 1}.")
    return "\n".join(out) or f"{name} has no rows from r{start}."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook")
    parser.add_argument("sheet", nargs="?")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--rows", type=int, default=60)
    args = parser.parse_args(argv)
    print(run(Book(args.workbook), args.sheet, args.start, args.rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

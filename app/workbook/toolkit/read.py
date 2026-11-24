"""What some cells hold: a number, text, a formula or nothing; and whether the template locks them.

    venv/bin/python -m app.workbook.toolkit.read book.xlsx "SOFP-CuNonCu!C12" "SOFP-CuNonCu!D12"
"""
from __future__ import annotations

import sys

from app.workbook.toolkit.book import Book, NotFound, describe, parse_ref

MAX_CELLS = 40


def run(book: Book, refs: list[str]) -> str:
    out = []
    for ref in refs[:MAX_CELLS]:
        try:
            sheet, row, col = parse_ref(ref)
            out.append(f"{book.sheet_name(sheet)}!{col}{row}: {describe(book, sheet, row, col)}")
        except NotFound as exc:
            out.append(f"{ref}: {exc}")
    if len(refs) > MAX_CELLS:
        out.append(f"Only the first {MAX_CELLS} cells were read.")
    return "\n".join(out) or "Name at least one cell, such as SOFP-CuNonCu!C12."


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(run(Book(args[0]), args[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

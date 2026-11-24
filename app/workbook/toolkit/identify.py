"""Which known template a workbook is, or why it is not one.

    venv/bin/python -m app.workbook.toolkit.identify book.xlsx
"""
from __future__ import annotations

import sys

from app.filing.identify import KNOWN, PROBABLY, identify
from app.workbook.toolkit.book import Book


def run(book: Book) -> str:
    found = identify(book.cells)
    if found.compatibility == KNOWN:
        head = f"Known template: {found.name}."
    elif found.compatibility == PROBABLY:
        head = "Not a known template, but laid out the mTool way."
    else:
        head = "Unknown template."
    lines = [head, *[f"- {reason}" for reason in found.reasons],
             f"{len(book.cells)} sheets. list_rows with no sheet lists them."]
    return "\n".join(lines)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print(run(Book(args[0])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

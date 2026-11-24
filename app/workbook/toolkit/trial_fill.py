"""Write values into a temporary copy of the workbook, read them back, and say what happened to each.
The workbook itself is never changed.

    venv/bin/python -m app.workbook.toolkit.trial_fill book.xlsx "SOFP-CuNonCu!C12=1200"
"""
from __future__ import annotations

import os
import sys
import tempfile

from app.workbook import offline_fill
from app.workbook.toolkit.book import Book, NotFound, parse_ref


def run(book: Book, writes: list[tuple[str, float]]) -> str:
    doc, out = [], []
    for ref, value in writes:
        try:
            sheet, row, col = parse_ref(ref)
            doc.append({"sheet": book.sheet_name(sheet), "cell": f"{col}{row}", "value": value, "line": ref})
        except NotFound as exc:
            out.append(f"{ref}: {exc}")
    if not doc:
        return "\n".join(out) or "Give at least one write, such as SOFP-CuNonCu!C12=1200."
    fd, copy = tempfile.mkstemp(prefix=".trial-", suffix=book.path.suffix)
    os.close(fd)
    try:
        result = offline_fill.fill_workbook(str(book.path), {"writes": doc}, copy)
    finally:
        os.unlink(copy)
    for key, words in (("written", "written and read back"), ("skipped_formula", "not written: it holds a formula"),
                       ("locked", "not written: the template locks it"),
                       ("mismatches", "written but read back differently")):
        out += [f"{w['line']}: {words}" for w in result[key]]
    out += [f"{w['line']}: not written: {w['error']}" for w in result["errors"]]
    return "\n".join(out)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    writes = [(ref, float(value)) for ref, value in (a.rsplit("=", 1) for a in args[1:])]
    print(run(Book(args[0]), writes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

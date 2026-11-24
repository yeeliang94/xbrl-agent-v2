"""The cells that differ between two workbooks, on every sheet or one.

    venv/bin/python -m app.workbook.toolkit.compare a.xlsx b.xlsx [--sheet SOFP-CuNonCu]
"""
from __future__ import annotations

import argparse

from app.workbook.toolkit.book import Book
from app.workbook.xlsx_cells import col_to_idx

MAX_DIFFERENCES = 60


def _shown(cell) -> str:
    kind, text = cell or ("", "")
    return {"F": "formula", "N": text, "S": repr(text[:40]), "E": "empty", "": "empty"}[kind]


def run(a: Book, b: Book, sheet: str | None = None) -> str:
    sheets = [sheet] if sheet else sorted(set(a.cells) | set(b.cells))
    out = []
    for name in sheets:
        if name not in a.cells or name not in b.cells:
            out.append(f"{name}: only in {'the second' if name in b.cells else 'the first'} workbook")
            continue
        left, right = a.cells[name], b.cells[name]
        for row in sorted(set(left) | set(right)):
            for col in sorted(set(left.get(row, {})) | set(right.get(row, {})), key=col_to_idx):
                x, y = left.get(row, {}).get(col), right.get(row, {}).get(col)
                if (x or ("E", ""))[0:2] != (y or ("E", ""))[0:2] and _shown(x) != _shown(y):
                    out.append(f"{name}!{col}{row}: {_shown(x)} -> {_shown(y)}")
    if not out:
        return "The two workbooks hold the same cells."
    more = f"\n{len(out) - MAX_DIFFERENCES} more differences; name a sheet." if len(out) > MAX_DIFFERENCES else ""
    return "\n".join(out[:MAX_DIFFERENCES]) + more


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("--sheet")
    args = parser.parse_args(argv)
    print(run(Book(args.first), Book(args.second), args.sheet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

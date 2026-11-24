"""Rows whose label or SSM name holds all the words given, on every sheet or one.

    venv/bin/python -m app.workbook.toolkit.find book.xlsx trade receivables [--sheet SOFP-CuNonCu]
"""
from __future__ import annotations

import argparse
import re

from app.workbook.toolkit.book import Book
from app.workbook.toolkit.list_rows import row_line

MAX_HITS = 25


def _words(text: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")   # SSM names run their words together
    return re.findall(r"[a-z0-9]+", spaced.lower())


def run(book: Book, words: list[str], sheet: str | None = None) -> str:
    wanted = [w.lower() for w in _words(" ".join(words))]
    if not wanted:
        return "Give at least one word to find."
    sheets = [book.sheet_name(sheet)] if sheet else list(book.cells)
    hits = []
    for name in sheets:
        for row, cells in sorted(book.cells[name].items()):
            have = _words(" ".join(text for kind, text in cells.values() if kind == "S"))
            if all(any(h.startswith(w) for h in have) for w in wanted):
                hits.append(f"{name} {row_line(book, name, row)}")
    if not hits:
        return f"No row holds all of: {' '.join(wanted)}. Try fewer or other words."
    more = f"\n{len(hits) - MAX_HITS} more; add words or name a sheet." if len(hits) > MAX_HITS else ""
    return "\n".join(hits[:MAX_HITS]) + more


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook")
    parser.add_argument("words", nargs="+")
    parser.add_argument("--sheet")
    args = parser.parse_args(argv)
    print(run(Book(args.workbook), args.words, args.sheet))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

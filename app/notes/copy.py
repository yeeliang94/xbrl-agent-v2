"""Note blocks copied from a run's stored page content (`pages.content_json`).

Code copies the words; no agent types them. A source block is named by its
PDF page and its position in that page's blocks. Tables arrive from the
Reader as HTML with rowspan and colspan; merged cells are split here, the
text in the first cell of the merge and the others empty, so every amount
stays in the column it is printed in (decision record 4, item 2).

The look starts plain. Only two safe guesses are made, both from the
table's own structure: a column whose cells are all amounts is an amount
column, and a row of header cells (<th>) is a heading row. The notes agent
sets the rest of the look later.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable, Optional, Sequence

from app.notes.blocks import (Cell, Column, Heading, ListBlock, ListItem, NoteBlock, Paragraph, Row, Source,
                              Table)
from app.reading.content import clean_text

__all__ = ["NotFromRun", "block_id", "copy_block", "copy_blocks", "table_grid", "page_blocks"]


class NotFromRun(LookupError):
    """A source block that is not on a page of this run. `str()` is one plain sentence."""


def block_id(page: int, block: int) -> str:
    return f"p{page}b{block}"


def not_from_run(page: object, block: object) -> str:
    return f"Page {page} of this run has no block {block}, so place blocks shown on this run's pages."


# Tables --------------------------------------------------------------------

@dataclass
class _Cell:
    text: str
    header: bool
    rowspan: int = 1
    colspan: int = 1


@dataclass
class _Grid:
    """A table's cells on a rectangular grid, merges split."""
    rows: list[list[str]] = field(default_factory=list)
    header_rows: list[bool] = field(default_factory=list)


class _SpanReader(HTMLParser):
    """Reads the Reader's cleaned table HTML into rows of cells with their spans."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self._cell: Optional[_Cell] = None
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            spans = {name: int(value) for name, value in attrs
                     if name in ("rowspan", "colspan") and (value or "").isdigit() and int(value) >= 1}
            self._cell = _Cell("", tag == "th", spans.get("rowspan", 1), spans.get("colspan", 1))
            self._parts = []
        elif tag == "br" and self._cell is not None:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._cell.text = clean_text("".join(self._parts))
            if self.rows:
                self.rows[-1].append(self._cell)
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._parts.append(data)


def table_grid(html: str) -> _Grid:
    """Rows of cell texts on one grid. A merged cell's text goes in its
    top-left cell; the cells it covers are empty. Short rows are padded."""
    reader = _SpanReader()
    reader.feed(html or "")
    reader.close()
    taken: dict[tuple[int, int], str] = {}
    covered: set[tuple[int, int]] = set()
    header: list[bool] = []
    width = 0
    for r, cells in enumerate(reader.rows):
        c = 0
        for cell in cells:
            while (r, c) in covered:
                c += 1
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    covered.add((r + dr, c + dc))
            taken[(r, c)] = cell.text
            c += cell.colspan
            width = max(width, c)
        header.append(bool(cells) and all(cell.header for cell in cells))
    height = max([r for r, _ in covered], default=-1) + 1
    grid = _Grid()
    for r in range(height):
        row = [taken.get((r, c), "") for c in range(width)]
        if r >= len(reader.rows) and not any(row):
            continue  # a rowspan running past the last <tr> adds no row of its own
        grid.rows.append(row)
        grid.header_rows.append(header[r] if r < len(header) else False)
    return grid


_AMOUNT = re.compile(r"^\(?-?\s*[0-9][0-9,]*(\.[0-9]+)?\s*\)?%?$|^[-–—]$|^nil$", re.IGNORECASE)


def _is_amount(text: str) -> bool:
    return bool(_AMOUNT.match(text.replace(" ", "")))


def _column_roles(rows: Sequence[Sequence[str]], header_rows: Sequence[bool], width: int) -> list[str]:
    body = [row for row, head in zip(rows, header_rows) if not head]
    roles = []
    for c in range(width):
        texts = [row[c] for row in body if row[c]]
        roles.append("amount" if texts and all(_is_amount(t) for t in texts) else "text")
    if roles and roles[0] == "text" and any(r == "amount" for r in roles[1:]):
        roles[0] = "label"
    return roles


def _table(block: dict, source: Source) -> Table:
    grid = table_grid(block.get("html", ""))
    if not grid.rows or not grid.rows[0]:
        raise ValueError("The table has no cells to copy.")
    width = len(grid.rows[0])
    roles = _column_roles(grid.rows, grid.header_rows, width)
    return Table(id=block_id(source.page, source.block), source=source,
                 columns=[Column(role=role) for role in roles],
                 rows=[Row(role="heading" if head else "item", cells=[Cell(text=t) for t in row])
                       for row, head in zip(grid.rows, grid.header_rows)])


# Blocks ----------------------------------------------------------------------

def copy_block(block: dict, page: int, index: int) -> NoteBlock:
    """One block of a page's content as a note block, with the plain look."""
    source = Source(page=page, block=index)
    bid = block_id(page, index)
    kind = block.get("type")
    if kind == "heading":
        return Heading(id=bid, source=source, level=min(3, max(1, int(block.get("level") or 2))), text=block["text"])
    if kind == "paragraph":
        return Paragraph(id=bid, source=source, text=block["text"])
    if kind == "list":
        return ListBlock(id=bid, source=source, items=[ListItem(text=item) for item in block.get("items", [])])
    if kind == "table":
        return _table(block, source)
    raise ValueError(f"Block {index} on page {page} is of an unknown kind.")


def page_blocks(conn: sqlite3.Connection, run_id: int, pages: Iterable[int]) -> dict[int, list[dict]]:
    """{page: its content blocks} for the given pages of this run that were read."""
    wanted = sorted({int(p) for p in pages if type(p) is int})
    if not wanted:
        return {}
    rows = conn.execute(
        "SELECT p.page, p.content_json FROM pages p JOIN documents d ON d.id = p.document_id "
        f"WHERE d.run_id = ? AND p.content_json IS NOT NULL AND p.page IN ({', '.join('?' * len(wanted))})",
        (run_id, *wanted)).fetchall()
    return {r["page"]: json.loads(r["content_json"]).get("blocks", []) for r in rows}


def copy_blocks(conn: sqlite3.Connection, run_id: int, sources: Sequence[tuple[int, int]]) -> list[NoteBlock]:
    """The note blocks for (page, block index) pairs of this run, in the order
    given. Raises NotFromRun for a pair not on a page of this run."""
    pairs = []
    for pair in sources:
        page, index = (pair.page, pair.block) if isinstance(pair, Source) else pair
        if type(page) is not int or type(index) is not int:
            raise NotFromRun(not_from_run(page, index))
        pairs.append((page, index))
    content = page_blocks(conn, run_id, [p for p, _ in pairs])
    out = []
    for page, index in pairs:
        blocks = content.get(page)
        if blocks is None or not 0 <= index < len(blocks):
            raise NotFromRun(not_from_run(page, index))
        out.append(copy_block(blocks[index], page, index))
    return out

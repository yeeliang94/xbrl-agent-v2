"""The reading copy: pages the server lays out itself from a Word or Excel file.

Nothing is converted with Word or LibreOffice (owner, 25 November 2026). The
file's content is written as plain HTML and laid out as A4 pages by PyMuPDF.
The reading copy gives a reviewer something to look at and gives every
figure a source page, so page-based reading, the page tools, the source rule
and the review screen work as they do for a PDF. Its page numbers are its
own, not the printed report's.

Beside the pages, the file's own words and numbers are kept as `Line`s, each
with the reading-copy page it landed on (`app/documents/file_lines.py`
stores them), so an agent takes a number from the file, not from a picture.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from html import escape
from typing import Optional

import pymupdf

from app.documents.pdf_check import MAX_PAGES

HEADING, TEXT, ROW = "heading", "text", "row"

A4 = pymupdf.paper_rect("a4")
A4_WIDE = pymupdf.paper_rect("a4-l")
MARGIN = 40
# A table with more columns than this is laid out on a wide (landscape) page.
WIDE_FROM_COLUMNS = 8
# A table row cannot break across pages, so a row with a cell longer than this is drawn as paragraphs.
LONG_CELL = 1200

CSS = """
body { font-family: sans-serif; font-size: 9pt; line-height: 1.3; }
h1 { font-size: 13pt; } h2 { font-size: 11pt; } h3, h4, h5, h6 { font-size: 10pt; }
p { margin: 3pt 0; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0; }
td, th { padding: 1pt 3pt; vertical-align: top; text-align: left; font-weight: normal; }
td.n, th.n { text-align: right; }
td.ref, th.ref { color: #6B7280; text-align: right; }
th.col { color: #6B7280; text-align: center; }
"""

# An amount as a statement prints it: digits with commas, brackets or a minus, a dash for nil.
_AMOUNT = re.compile(r"^\(?-?[\d][\d,]*(\.\d+)?\)?%?$|^[-–—]$")


def parse_amount(text: str) -> Optional[float]:
    """The number a shown amount stands for: (1,234) is -1234, 12.5% is 0.125."""
    body = text.strip()
    negative = body.startswith("(") and body.endswith(")") or body.startswith("-")
    percent = body.endswith("%")
    digits = body.strip("()-% ").replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", digits):
        return None
    value = float(digits) / (100 if percent else 1)
    return -value if negative else value


def looks_numeric(text: str) -> bool:
    return bool(_AMOUNT.match(text.strip()))


@dataclass
class Line:
    """One heading, paragraph or table row of the file, as the file holds it."""
    kind: str                                  # heading, text or row
    cells: list                                # Word: the texts in order. Excel: [column letter, shown, saved value]
    block: int = 0                             # Word: the table's number, from 1; 0 outside a table
    sheet: Optional[str] = None                # Excel: the sheet's name
    row: Optional[int] = None                  # the row in its table (Word) or on its sheet (Excel), from 1
    page: int = 0                              # the reading-copy page it is laid out on


@dataclass
class Part:
    """A stretch of the file laid out from the top of a new page: the whole Word file, or one sheet."""
    html: str
    lines: dict[str, Line]                     # by the id of its HTML element
    wide: bool = False
    pictures: dict[str, bytes] = field(default_factory=dict)   # by the name the HTML's <img> uses


@dataclass
class ReadingCopy:
    pdf: bytes
    page_count: int
    lines: list[Line]
    part_pages: list[tuple[int, int]]          # each part's first and last page


def cell_html(text: str, tag: str = "td", css: str = "") -> str:
    classes = " ".join(c for c in (css, "n" if looks_numeric(text) else "") if c)
    return f"<{tag}{f' class=\"{classes}\"' if classes else ''}>{escape(text)}</{tag}>"


def lay_out(parts: list[Part]) -> ReadingCopy:
    """Lay the parts out as PDF pages, each part from a new page, and say which page every line is on."""
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page, lines, part_pages = 0, [], []
    for part in parts:
        archive = pymupdf.Archive()
        for name, data in part.pictures.items():
            archive.add(data, name)
        story = pymupdf.Story(html=part.html, user_css=CSS, archive=archive)
        box = A4_WIDE if part.wide else A4
        where = box + (MARGIN, MARGIN, -MARGIN, -MARGIN)
        first, placed, more = page + 1, {}, 1
        # Stopped one page past the limit, which the caller refuses: a page that never fills cannot loop.
        while more and page <= MAX_PAGES:
            page += 1
            device = writer.begin_page(box)
            more, _ = story.place(where)
            # Every element is reported on every page, those not yet placed with a place below the
            # page's foot. An element belongs to the first page it sits on.
            story.element_positions(
                lambda position: placed.setdefault(position.id, position.page)
                if position.id in part.lines and position.open_close & 1 and position.rect[1] < where.y1 - 1
                else None, {"page": page})
            story.draw(device)
            writer.end_page()
        for key, line in part.lines.items():
            line.page = placed.get(key, page)
            lines.append(line)
        part_pages.append((first, page))
    writer.close()
    return ReadingCopy(pdf=buffer.getvalue(), page_count=page, lines=lines, part_pages=part_pages)

"""A Word document (.docx) as a reading copy and its own lines.

`mammoth` turns the document's body into plain HTML (headings, paragraphs,
lists, tables, pictures); `python-docx` opens the file first, so a broken
one is refused before anything is laid out. Text a tracked change deleted is
left out and text it inserted is kept, as the document reads with every
change accepted. Page headers and footers are not part of the body and are
left out.
"""
from __future__ import annotations

import io
from html import escape

import docx
import mammoth
from bs4 import BeautifulSoup, Tag

from app.documents import reading_copy as rc
from app.documents.source_file import WORD, Refused, unreadable
from app.documents.workbook_copy import unzipped_too_large

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_PICTURE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/bmp": "bmp"}


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ").split())


def _html_and_pictures(data: bytes) -> tuple[str, dict[str, bytes]]:
    pictures: dict[str, bytes] = {}

    def keep(image) -> dict:
        extension = _PICTURE_TYPES.get(image.content_type)
        if extension is None:        # a drawing format PyMuPDF cannot place (EMF, WMF): left out
            return {"src": ""}
        name = f"picture-{len(pictures) + 1}.{extension}"
        with image.open() as handle:
            pictures[name] = handle.read()
        return {"src": name}

    result = mammoth.convert_to_html(io.BytesIO(data), convert_image=mammoth.images.img_element(keep))
    return result.value, pictures


class _Builder:
    def __init__(self) -> None:
        self.out: list[str] = []
        self.lines: dict[str, rc.Line] = {}
        self.tables = 0
        self.widest = 0

    def _id(self, line: rc.Line) -> str:
        key = f"b{len(self.lines) + 1}"
        self.lines[key] = line
        return key

    def _pictures(self, tag: Tag) -> str:
        return "".join(f'<p><img src="{escape(img["src"], quote=True)}"></p>'
                       for img in tag.find_all("img") if img.get("src"))

    def block(self, tag: Tag) -> None:
        name = tag.name
        if name in _HEADINGS:
            text = _text(tag)
            if text:
                key = self._id(rc.Line(rc.HEADING, [text]))
                self.out.append(f'<{name} id="{key}">{escape(text)}</{name}>')
        elif name == "p":
            text = _text(tag)
            if text:
                key = self._id(rc.Line(rc.TEXT, [text]))
                bold = tag.find(["strong", "b"]) is not None and _text(tag.find(["strong", "b"])) == text
                inner = f"<b>{escape(text)}</b>" if bold else escape(text)
                self.out.append(f'<p id="{key}">{inner}</p>')
            self.out.append(self._pictures(tag))
        elif name in ("ul", "ol"):
            for number, item in enumerate(tag.find_all("li", recursive=False), start=1):
                text = _text(item)
                if text:
                    mark = f"{number}." if name == "ol" else "-"
                    key = self._id(rc.Line(rc.TEXT, [f"{mark} {text}"]))
                    self.out.append(f'<p id="{key}">{mark} {escape(text)}</p>')
                self.out.append(self._pictures(item))
        elif name == "table":
            self.table(tag)
        else:                        # a wrapper mammoth made: its blocks one by one
            for child in tag.find_all(True, recursive=False):
                self.block(child)

    def table(self, tag: Tag) -> None:
        self.tables += 1
        rows = []
        for number, tr in enumerate(tag.find_all("tr"), start=1):
            if tr.find_parent("table") is not tag:      # a table inside a cell reads as that cell's text
                continue
            cells = [c for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]
            texts = [_text(c) for c in cells]
            # A picture in a cell (a statement pasted as an image) is drawn below its row.
            pictures = "".join(self._pictures(c) for c in cells)
            if not any(texts):
                if pictures:
                    self._close(rows)
                    self.out.append(pictures)
                continue
            self.widest = max(self.widest, sum(int(c.get("colspan") or 1) for c in cells))
            key = self._id(rc.Line(rc.ROW, texts, block=self.tables, row=number))
            if max(len(text) for text in texts) > rc.LONG_CELL:
                # A table row cannot break across pages, so a row taller than a page would be cut off.
                # It is drawn as paragraphs instead, which can; the row's line keeps its cells.
                self._close(rows)
                paragraphs = "".join(f"<p>{escape(text)}</p>" for text in texts if text)
                self.out.append(f'<div id="{key}">{paragraphs}{pictures}</div>')
                continue
            drawn = []
            for cell, text in zip(cells, texts):
                html = rc.cell_html(text)
                span = "".join(f' {name}="{int(cell[name])}"' for name in ("colspan", "rowspan")
                               if str(cell.get(name) or "").isdigit() and int(cell[name]) > 1)
                drawn.append(html.replace("<td", f"<td{span}", 1) if span else html)
            rows.append(f'<tr id="{key}">{"".join(drawn)}</tr>')
            if pictures:
                self._close(rows)
                self.out.append(pictures)
        self._close(rows)

    def _close(self, rows: list[str]) -> None:
        """Draw the table rows gathered so far and start afresh."""
        if rows:
            self.out.append(f"<table>{''.join(rows)}</table>")
            rows.clear()


def word_copy(filename: str, data: bytes) -> rc.ReadingCopy:
    """The reading copy of a .docx file, or Refused when it cannot be read or holds nothing to read."""
    unzipped_too_large(filename, data)
    try:
        docx.Document(io.BytesIO(data))
        html, pictures = _html_and_pictures(data)
    except Exception as exc:  # noqa: BLE001 - both libraries raise several types for a broken file
        raise unreadable(filename, WORD) from exc
    builder = _Builder()
    for tag in BeautifulSoup(html, "html.parser").find_all(True, recursive=False):
        builder.block(tag)
    if not builder.lines:
        raise Refused(f"{filename} holds no text or tables to read.")
    part = rc.Part(html="".join(builder.out), lines=builder.lines, wide=builder.widest > rc.WIDE_FROM_COLUMNS,
                   pictures=pictures)
    return rc.lay_out([part])

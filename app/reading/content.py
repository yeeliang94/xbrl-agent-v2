"""A page's structured content: what transcription returns and `pages.content_json` holds.

Validated strictly. Each problem is one plain sentence the model can act on
when it is asked to correct its answer. Special spaces (non-breaking,
ideographic U+3000 and the like) become ordinary spaces. A table is kept as
HTML holding only table structure: rows, cells and their spans.
"""
from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

PageKind = Literal["cover", "contents", "directors_report", "statement_by_directors", "statutory_declaration",
                   "auditors_report", "statement", "notes", "other"]
BlockType = Literal["heading", "paragraph", "list", "table"]
MarkKind = Literal["stamp", "signature", "handwriting", "logo"]
TextTop = Literal["top", "left", "bottom", "right"]

# The clockwise turn that brings the top of the letters, pointing at this
# edge of the picture, to the top. A model names the edge more reliably than
# it names a clockwise angle (Doc 1 page 17 came back 270 for 90 in three runs
# out of three, 23 November 2026), so it names the edge and code turns it.
TURN_FOR_TEXT_TOP = {"top": 0, "left": 90, "bottom": 180, "right": 270}

# Seen in v1's live transcriptions: U+3000 from GPT models, plus the usual
# non-breaking and fixed-width spaces. Zero-width characters are dropped.
_ODD_SPACES = re.compile("[   -   　]")
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")

TABLE_TAGS = frozenset({"table", "thead", "tbody", "tfoot", "tr", "th", "td"})
_VOID_TAGS = frozenset({"br"})
# Inline styling inside a cell is dropped and its words kept: the look of a
# note is copied in step 6, from the page itself (as v1's normaliser did).
_DROPPED_TAGS = frozenset({"b", "strong", "i", "em", "u", "s", "span", "font", "sup", "sub", "small", "p", "div"})
_CELL_ATTRS = frozenset({"rowspan", "colspan"})


def clean_text(text: str) -> str:
    text = _ZERO_WIDTH.sub("", _ODD_SPACES.sub(" ", text or ""))
    return re.sub(r"[ \t]+", " ", text).strip()


class _TableReader(HTMLParser):
    """Checks table HTML and rebuilds it with only table structure. Collects
    each row's cell texts as it goes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.problems: list[str] = []
        self.rows: list[list[str]] = []
        self._cell: Optional[list[str]] = None
        self.tables = 0

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if self._cell is not None:
                self._cell.append(" ")
            self.out.append("<br>")
            return
        if tag in _DROPPED_TAGS:
            return
        if tag not in TABLE_TAGS:
            self.problems.append(f"A table may hold only table, thead, tbody, tfoot, tr, th, td and br tags, "
                                 f"not <{tag}>.")
            return
        if tag == "table":
            self.tables += 1
        if tag == "tr":
            self.rows.append([])
        if tag in ("td", "th"):
            if not self.stack or self.stack[-1] != "tr":
                self.problems.append(f"Each <{tag}> must sit directly inside a <tr>.")
            self._cell = []
        kept = []
        for name, value in attrs:
            if name in _CELL_ATTRS and tag in ("td", "th"):
                if not (value or "").isdigit() or int(value) < 1:
                    self.problems.append(f"{name} must be a whole number of 1 or more, not {value!r}.")
                    continue
                kept.append(f' {name}="{int(value)}"')
        self.stack.append(tag)
        self.out.append(f"<{tag}{''.join(kept)}>")

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS or tag not in TABLE_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"The table's tags are not closed in order: </{tag}> does not match.")
            return
        self.stack.pop()
        if tag in ("td", "th") and self._cell is not None:
            if self.rows:
                self.rows[-1].append(clean_text("".join(self._cell)))
            self._cell = None
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
            self.out.append(escape(re.sub(r"\s+", " ", _ZERO_WIDTH.sub("", _ODD_SPACES.sub(" ", data))), quote=False))
        elif data.strip():
            self.problems.append("Table text must sit inside a <td> or <th> cell.")


def read_table(html: str) -> tuple[str, list[list[str]], list[str]]:
    """(cleaned HTML, rows of cell texts, problems)."""
    reader = _TableReader()
    reader.feed(_ODD_SPACES.sub(" ", html or ""))
    reader.close()
    problems = list(dict.fromkeys(reader.problems))
    if reader.stack:
        problems.append("The table's tags are not all closed.")
    if reader.tables != 1:
        problems.append("Each table block must hold exactly one <table>.")
    if not reader.rows:
        problems.append("A table needs at least one <tr> row.")
    return "".join(reader.out), reader.rows, problems


class Box(BaseModel):
    """A region in page fractions of the upright page: left, top, right, bottom."""
    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _in_order(self):
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("A region needs left below right and top below bottom, as page fractions.")
        return self


class Block(BaseModel):
    type: BlockType
    text: str = Field(default="", description="The words of a heading or paragraph, verbatim.")
    level: int = Field(default=0, ge=0, le=3, description="Heading level: 1 page title, 2 section or note, 3 sub-note.")
    items: list[str] = Field(default_factory=list, description="A list's items, verbatim, numbering included.")
    html: str = Field(default="", description="A table as HTML: table, tr, th, td and br only, with rowspan or colspan.")

    @model_validator(mode="after")
    def _shape(self):
        self.text = clean_text(self.text)
        self.items = [clean_text(i) for i in self.items if clean_text(i)]
        if self.type in ("heading", "paragraph") and not self.text:
            raise ValueError(f"A {self.type} block needs its text.")
        if self.type == "heading" and self.level == 0:
            self.level = 2
        if self.type == "list" and not self.items:
            raise ValueError("A list block needs its items.")
        if self.type == "table":
            html, _, problems = read_table(self.html)
            if problems:
                raise ValueError(" ".join(problems))
            self.html = html
        return self


class Uncertain(BaseModel):
    seen: str = Field(description="What is visible, with ? for each character that cannot be made out.")
    reading: str = Field(description="The best reading, as used in the blocks, or empty when none is plausible.")

    @field_validator("seen", "reading")
    @classmethod
    def _clean(cls, v: str) -> str:
        return clean_text(v)


class Mark(BaseModel):
    kind: MarkKind
    box: Box


class PageContent(BaseModel):
    """One page, read once. Running headers and footers are left out of the
    blocks and recorded in `running_text`."""
    folio: Optional[str] = Field(description="The page number printed on the page, as printed, or null when none is printed.")
    text_top: TextTop = Field(
        default="top", description="The edge of the picture that the top of the letters points to: top when the "
                                   "page reads normally, left or right when it is sideways, bottom when upside down.")
    # Worked out from text_top, never asked of the model; kept as stored content's field.
    rotation: SkipJsonSchema[Literal[0, 90, 180, 270]] = 0
    kind: PageKind
    title: str = Field(default="", description="The page's main heading, or empty.")
    blocks: list[Block] = Field(default_factory=list)
    running_text: list[str] = Field(
        default_factory=list, description="Running headers and footers left out of the blocks, such as a company "
                                          "banner repeated on every page and the printed page number.")
    uncertain: list[Uncertain] = Field(default_factory=list)
    marks: list[Mark] = Field(default_factory=list, description="Stamps, signatures, handwriting and logos, as regions.")

    @model_validator(mode="after")
    def _clean(self):
        if "text_top" in self.model_fields_set or "rotation" not in self.model_fields_set:
            self.rotation = TURN_FOR_TEXT_TOP[self.text_top]
        self.title = clean_text(self.title)
        self.folio = clean_text(self.folio) or None if self.folio is not None else None
        self.running_text = [clean_text(t) for t in self.running_text if clean_text(t)]
        if not self.blocks and self.kind != "other":
            raise ValueError("The page has content, so give its blocks; a page with nothing to read has kind other.")
        return self


def blank_page() -> dict:
    """The stored content of a page with no ink: no model call is made."""
    return {"blank": True, "folio": None, "rotation": 0, "kind": "blank", "title": "", "blocks": [],
            "running_text": [], "uncertain": [], "marks": []}


# Reading content back ------------------------------------------------------

def table_rows(block: dict) -> list[list[str]]:
    return read_table(block.get("html", ""))[1] if block.get("type") == "table" else []


def plain_text(content: dict) -> str:
    """The page's words, for search."""
    parts = [content.get("title", "")]
    for block in content.get("blocks", []):
        if block["type"] == "table":
            parts.extend(" | ".join(row) for row in table_rows(block))
        elif block["type"] == "list":
            parts.extend(block.get("items", []))
        else:
            parts.append(block.get("text", ""))
    parts.extend(content.get("running_text") or [])
    return "\n".join(p for p in parts if p)


def as_reading(content: dict) -> str:
    """The page as an agent reads it: headings marked with #, tables as HTML."""
    lines: list[str] = []
    for block in content.get("blocks", []):
        if block["type"] == "heading":
            lines.append("#" * max(1, block.get("level") or 2) + " " + block["text"])
        elif block["type"] == "paragraph":
            lines.append(block["text"])
        elif block["type"] == "list":
            lines.extend(f"- {item}" for item in block.get("items", []))
        else:
            lines.append(block.get("html", ""))
    if content.get("uncertain"):
        lines.append("Uncertain words: " + "; ".join(
            f"saw {u['seen']!r}, read as {u['reading']!r}" if u.get("reading") else f"saw {u['seen']!r}, no reading"
            for u in content["uncertain"]))
    if content.get("marks"):
        lines.append("Marks (not text): " + ", ".join(m["kind"] for m in content["marks"]))
    if content.get("running_text"):
        # Letterheads, banners and page numbers are kept out of the blocks, but they can hold facts a report
        # field needs (an audit firm's address on its letterhead), so an agent sees them, marked as such.
        lines.append("Printed around the page (letterhead, banners, page number): "
                     + " | ".join(content["running_text"]))
    return "\n".join(lines)

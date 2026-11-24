"""The one renderer for notes (docs/step-6-plan.md 6c).

`prepare` turns a field's notes into the one HTML text that the review page,
the Copy button and mTool all use, sized to mTool's limit. `review_html` is
that text with marks the review page selects by, and nothing else: taking the
marks off gives the prepared text back exactly. `preview` draws that same
text on mTool's page for the notes agent.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.notes.blocks import NoteBody
from app.notes.render.decorate import NotesTableStyle, from_house
from app.notes.render import fit as _fitting
from app.notes.render.fit import EXCEL_CELL_CHAR_LIMIT
from app.notes.render.html import REVIEW_MARKS, field_html
from app.notes.render.picture import draw, fitting_font_size, to_mm

__all__ = ["EXCEL_CELL_CHAR_LIMIT", "Prepared", "Preview", "house_style", "prepare", "preview", "review_html",
           "without_review_marks"]


@dataclass(frozen=True)
class Prepared:
    html: str             # the text for review, Copy and mTool, at `tier`
    tier: str             # full, compact, lite, flat, or too_long
    chars: int            # characters in mTool's cell, wrapped as the patcher writes it
    limit: int            # mTool's limit, 32,767
    too_long: bool        # no tier fits: the text is whole and uncut
    white_grid_dropped: bool
    revision: str         # sha256 of `html`, to prove two outputs are the same text
    source_html: str      # before mTool styling, for the font search
    style: NotesTableStyle


@dataclass(frozen=True)
class Preview:
    pages: list[bytes]    # PNG, one per mTool page
    overflow_mm: float    # how far the widest table runs past 170 mm; 0 when it fits
    fits_at_pt: int | None  # with overflow: the table font that fits, never below the minimum
    min_font_pt: int


def house_style() -> dict:
    """The notes house style from the Settings page."""
    from app.settings import store
    return store.read()["house_style"]


def _complete(house: dict | None) -> dict:
    from app.settings.store import DEFAULTS
    return {**copy.deepcopy(DEFAULTS["house_style"]), **(house or {})}


def prepare(field_notes: list[NoteBody], house: dict | None = None) -> Prepared:
    """One field's notes, in order, as one text. ``house`` is the Settings
    page's notes house style; missing values take the Settings defaults."""
    house = _complete(house)
    style = from_house(house)
    raw = field_html(field_notes, house)
    fitted = _fitting.fit(raw, style)
    return Prepared(
        html=fitted.html, tier=fitted.tier, chars=fitted.chars, limit=EXCEL_CELL_CHAR_LIMIT,
        too_long=fitted.tier == "too_long", white_grid_dropped=fitted.white_grid_dropped,
        revision=hashlib.sha256(fitted.html.encode("utf-8")).hexdigest(),
        source_html=raw, style=style,
    )


def without_review_marks(html: str) -> str:
    """The review text with its marks taken off: the prepared text."""
    soup = BeautifulSoup(html, "html.parser")
    for attr in REVIEW_MARKS:
        for el in soup.find_all(attrs={attr: True}):
            del el[attr]
    return str(soup)


def review_html(field_notes: list[NoteBody], note_ids: list[int], prepared: Prepared,
                house: dict | None = None) -> str:
    """The field's prepared text as the review page draws it: the same text at
    the same tier, each block marked with its note and block, each table cell
    with its row and column. Raises if taking the marks off would not give
    ``prepared.html`` back, so review can never show a different text."""
    house = _complete(house)
    marked = field_html(field_notes, house, note_ids)
    html = _fitting.at_tier(marked, prepared.style, prepared.tier, prepared.white_grid_dropped)
    if without_review_marks(html) != str(BeautifulSoup(prepared.html, "html.parser")):
        raise ValueError("The review text is not the prepared text.")
    return html


def preview(prepared: Prepared) -> Preview:
    """Pictures of the prepared text on mTool's page, its overflow, and the
    table font at which it would fit."""
    pages, overflow = draw(prepared.html)
    fits_at = fitting_font_size(prepared.source_html, prepared.style) if overflow else None
    return Preview(pages=pages, overflow_mm=to_mm(overflow), fits_at_pt=fits_at,
                   min_font_pt=prepared.style.min_font_pt)

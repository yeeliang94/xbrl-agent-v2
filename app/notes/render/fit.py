"""Fit a field's text inside mTool's limit by dropping styling, never words.

mTool keeps one text per field in an Excel cell, and Excel refuses a cell
over 32,767 characters. The count is on the whole wrapped text the patcher
writes (`wrap_footnote_html`), not on what a reader sees. The tiers are v1's:
full, then compact, then lite, then the same three without the white grid,
then flat (no inline styling; bold, italic and underline stay). A field that is still over is too long for mTool:
nothing is cut, and splitting it is a content decision for a person.

`wrap_footnote_html` and `EXCEL_CELL_CHAR_LIMIT` come from the patcher
(`app/workbook/offline_fill.py`). Copied from v1: `prepare_note_output` and
`_resolve_note_html` (`mtool/notes_exporter.py` 344-467, less the database
reads and the Word-table destyle retry), `content_structure`
(`notes/format_verify.py` 155).
"""
from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, NavigableString

from app.notes.render.decorate import (
    NotesTableStyle, add_transport_breaks, decorate_notes_html, without_transport_breaks,
)
# mTool's text-block shell and Excel's cell limit live with the one patcher,
# so the length counted here is the length it writes.
from app.workbook.offline_fill import EXCEL_CELL_CHAR_LIMIT, wrap_footnote_html  # noqa: F401

TIERS = ("full", "compact", "lite", "flat")


def mtool_length(fragment: str) -> int:
    """The characters the field takes in mTool's cell."""
    return len(wrap_footnote_html(fragment))


def content_structure(html: str) -> tuple:
    """The words and structure of some HTML, ignoring styling and wrappers."""
    def walk(node):
        if isinstance(node, Comment):
            return ()
        if isinstance(node, NavigableString):
            return (("text", str(node)),)
        children = tuple(item for child in node.children for item in walk(child))
        if node.name in ("[document]", "div", "span"):
            return children
        name = {"b": "strong", "i": "em"}.get(node.name, node.name)
        return ((name, children),)

    return walk(BeautifulSoup(html, "html.parser"))


def strip_inline_styles(html: str) -> str:
    """The flat tier's text: every inline style removed, words, emphasis
    and structure kept."""
    if "style=" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(style=True):
        del el["style"]
    return str(soup)


class ContentChanged(ValueError):
    """Styling would have changed a note's words or structure."""


@dataclass(frozen=True)
class Fitted:
    html: str              # the text review, Copy and mTool all use
    tier: str              # full, compact, lite, flat; "too_long" when none fits
    chars: int             # mtool_length(html)
    white_grid_dropped: bool


def _walk(raw: str, style: NotesTableStyle) -> tuple[str, str, bool] | None:
    def fits(h: str) -> bool:
        return mtool_length(h) <= EXCEL_CELL_CHAR_LIMIT

    full = decorate_notes_html(raw, style)
    if fits(full):
        return full, "full", False
    # Compact differs from full only for a gridded table; skip it otherwise.
    compact = decorate_notes_html(raw, style, compact=True)
    if compact != full and fits(compact):
        return compact, "compact", False
    lite = decorate_notes_html(raw, style, lite=True)
    if fits(lite):
        return lite, "lite", False
    # The white grid costs about 27 characters a cell: a grey grid in mTool
    # beats losing all styling.
    nofill = decorate_notes_html(raw, style, fill_white_grid=False)
    if nofill != full:
        if fits(nofill):
            return nofill, "full", True
        nofill_compact = decorate_notes_html(raw, style, compact=True, fill_white_grid=False)
        if nofill_compact != nofill and fits(nofill_compact):
            return nofill_compact, "compact", True
        nofill_lite = decorate_notes_html(raw, style, lite=True, fill_white_grid=False)
        if fits(nofill_lite):
            return nofill_lite, "lite", True
    flat = add_transport_breaks(strip_inline_styles(raw))
    if fits(flat):
        return flat, "flat", False
    return None


def at_tier(raw: str, style: NotesTableStyle, tier: str, white_grid_dropped: bool) -> str:
    """The text at a tier `fit` already chose: for the review variant of the
    same field, whose marks must not change which tier it lands on."""
    if tier == "too_long":
        return raw
    if tier == "flat":
        return add_transport_breaks(strip_inline_styles(raw))
    return decorate_notes_html(raw, style, compact=tier == "compact", lite=tier == "lite",
                               fill_white_grid=not white_grid_dropped)


def fit(raw: str, style: NotesTableStyle) -> Fitted:
    """The styled text at the richest tier that fits, with the same words."""
    landed = _walk(raw, style)
    if landed is None:
        # Too long even plain: the whole text, uncut, reported too long.
        html, tier, dropped = raw, "too_long", False
    else:
        html, tier, dropped = landed
    if content_structure(raw) != content_structure(without_transport_breaks(html)):
        raise ContentChanged("Styling would have changed the note's words or structure.")
    return Fitted(html=html, tier=tier, chars=mtool_length(html), white_grid_dropped=dropped)

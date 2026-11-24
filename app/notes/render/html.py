"""A field's notes, as blocks, to plain HTML in the vocabulary mTool's note
editor accepts (docs/step-6-plan.md section 3, "Mapped to what mTool's note
editor accepts").

Only set looks are written here, inline, so the decorator's merges keep them.
A look that is absent, or listed as "not sure", is left out and the house
style draws it. Two house values are applied here because they decide a set
look's form or fill an absent one: how a double line draws, and bold totals.
"""
from __future__ import annotations

from html import escape

from app.notes.blocks import Heading, ListBlock, NoteBody, Paragraph, Table
from app.notes.render.decorate import FONT_SIZE_ATTR, GRID_ATTR, HOUSE_CELL_PADDING_PX
from app.notes.render.tables import WIDTHS_ATTR, is_numeric_cell_text

SINGLE_LINE = "0.75px solid #000000"
THICK_LINE = "2.5px solid #000000"
GRID_LINE = "0.75px solid #000000"
SHADE = "#f2f2f2"
# mTool's text width, 170 mm, in CSS pixels: stated column widths in percent
# become pixel widths of this whole for the decorator's width attributes.
TEXT_WIDTH_PX = 643
# A heading level 1 is v1's note heading (h3); deeper levels follow it.
_HEADING_TAG = {1: "h3", 2: "h4", 3: "h5"}


def _set(look, key: str):
    """The look's value, or None when the agent was not sure of it."""
    return None if key in look.unsure else getattr(look, key)


def _text(text: str) -> str:
    return escape(text).replace("\n", "<br>")


def _marks(inner: str, bold: bool, italic: bool, underline: bool) -> str:
    if underline:
        inner = f"<u>{inner}</u>"
    if italic:
        inner = f"<em>{inner}</em>"
    if bold:
        inner = f"<strong>{inner}</strong>"
    return inner


def _style_attr(parts: list[str]) -> str:
    return f' style="{"; ".join(parts)}"' if parts else ""


# The review page's marks: which note and block an element draws, and a
# cell's row and column, so a person can select it on the prepared text.
# Only the review variant carries them; `without_review_marks` takes them off.
REVIEW_MARKS = ("data-note", "data-block", "data-row", "data-col")


def _mark(where: tuple[int, int] | None) -> str:
    return f' data-note="{where[0]}" data-block="{where[1]}"' if where else ""


def _text_block_style(look) -> list[str]:
    parts = []
    if _set(look, "align"):
        parts.append(f"text-align: {look.align}")
    indent = _set(look, "indent")
    if indent:
        parts.append(f"margin-left: {2 * indent}em")
    return parts


def _heading(b: Heading, where=None) -> str:
    tag = _HEADING_TAG[b.level]
    look = b.look
    inner = _marks(_text(b.text), False, bool(_set(look, "italic")), bool(_set(look, "underline")))
    # A heading is always drawn bold; a set bold adds nothing.
    return f"<{tag}{_mark(where)}{_style_attr(_text_block_style(look))}>{inner}</{tag}>"


def _paragraph(b: Paragraph, where=None) -> str:
    look = b.look
    inner = _marks(_text(b.text), bool(_set(look, "bold")), bool(_set(look, "italic")),
                   bool(_set(look, "underline")))
    return f"<p{_mark(where)}{_style_attr(_text_block_style(look))}>{inner}</p>"


def _list(b: ListBlock, where=None) -> str:
    # Numbering and bullets are kept as printed, so the list draws no marker.
    look = b.look
    parts = ["list-style-type: none", "padding-left: 0", *_text_block_style(look)]
    items = []
    for item in b.items:
        inner = _marks(_text(item.text), bool(_set(look, "bold")), bool(_set(look, "italic")),
                       bool(_set(look, "underline")))
        indent = f' style="margin-left: {2 * item.level}em"' if item.level else ""
        items.append(f"<li{indent}>{inner}</li>")
    return f"<ul{_mark(where)}{_style_attr(parts)}>{''.join(items)}</ul>"


def _widths(t: Table) -> list[int] | None:
    """Pixel widths for every column, or None when no width is set. Columns
    without a set width share what the set ones leave."""
    stated = [_set(c, "width") for c in t.columns]
    if not any(stated):
        return None
    rest = max(0.0, 100 - sum(w for w in stated if w))
    open_cols = sum(1 for w in stated if not w)
    fill = rest / open_cols if open_cols else 0
    return [max(1, round((w or fill or 1) * TEXT_WIDTH_PX / 100)) for w in stated]


def _line(house: dict, style: str) -> str:
    if style == "double" and house["double_underline"] == "thick_bottom_border":
        return THICK_LINE
    return SINGLE_LINE


def _cell(t: Table, r_index: int, c_index: int, house: dict, marked: bool = False) -> str:
    row = t.rows[r_index]
    cell = row.cells[c_index]
    column = t.columns[c_index]
    role = _set(row, "role") or "item"
    tag = "th" if role == "heading" else "td"
    style: list[str] = []
    if t.frame == "grid" and "frame" not in t.unsure:
        style.append(f"border: {GRID_LINE}")
    line = _set(row, "line_below")
    if line and (not line.columns or c_index in line.columns):
        style.append(f"border-bottom: {_line(house, line.style)}")
    align = _set(cell.look, "align") or _set(column, "align")
    # Amounts align right. The decorator already does so for a figure, so
    # only other text in an amount column (a year heading) needs saying.
    if (not align and _set(column, "role") == "amount" and c_index > 0
            and not is_numeric_cell_text(cell.text)):
        align = "right"
    if align:
        style.append(f"text-align: {align}")
    valign = _set(cell.look, "valign")
    if valign:
        style.append(f"vertical-align: {valign}")
    if _set(row, "shaded"):
        style.append(f"background: {SHADE}")
    indent = _set(row, "indent")
    if indent and c_index == 0:
        # The whole padding, so the house padding cannot replace the indent.
        pad_v, pad_h = HOUSE_CELL_PADDING_PX
        style.append(f"padding: {pad_v}px {pad_h}px {pad_v}px {1.5 * indent:g}em")
    bold = bool(_set(row, "bold") or _set(cell.look, "bold"))
    if not bold and role == "total" and house["bold_totals"]:
        bold = True
    inner = _marks(_text(cell.text), bold, bool(_set(cell.look, "italic")),
                   bool(_set(cell.look, "underline")))
    mark = f' data-row="{r_index}" data-col="{c_index}"' if marked else ""
    return f"<{tag}{mark}{_style_attr(style)}>{inner}</{tag}>"


def _table(t: Table, house: dict, where=None) -> str:
    attrs = _mark(where)
    if t.frame == "grid" and "frame" not in t.unsure:
        attrs += f' {GRID_ATTR}="grid"'
    font = _set(t, "font_pt")
    if font:
        size = max(int(font), int(house["smallest_table_font_pt"]))
        attrs += f' {FONT_SIZE_ATTR}="{size}"'
    out = [f"<table{attrs}>"]
    widths = _widths(t)
    if widths:
        cols = "".join(f'<col style="width: {w}px">' for w in widths)
        out.append(f'<colgroup {WIDTHS_ATTR}="true">{cols}</colgroup>')
    out.append("<tbody>")
    for r in range(len(t.rows)):
        out.append("<tr>" + "".join(_cell(t, r, c, house, where is not None) for c in range(len(t.columns))) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def field_html(notes: list[NoteBody], house: dict, note_ids: list[int] | None = None) -> str:
    """Every note of one field, in order, as one HTML text. With ``note_ids``
    (one per note), the review variant: the same text with `REVIEW_MARKS`."""
    out: list[str] = []
    for n, note in enumerate(notes):
        for i, b in enumerate(note.blocks):
            where = (note_ids[n], i) if note_ids is not None else None
            if isinstance(b, Heading):
                out.append(_heading(b, where))
            elif isinstance(b, Paragraph):
                out.append(_paragraph(b, where))
            elif isinstance(b, ListBlock):
                out.append(_list(b, where))
            else:
                out.append(_table(b, house, where))
    return "".join(out)

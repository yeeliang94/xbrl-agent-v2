"""mTool styling for a note's HTML: fonts, cell padding, alignment, lines and
spacing, written inline in the dialect mTool's note editor (TX27) reads.

Copied from v1's `mtool/notes_decorate.py` (1,289 lines), less its Word-table
(`data-source-styled`, destyling), editor-resize, merged-cell and legacy-theme
paths. A look the note sets is written inline by html.py before this runs,
and every merge here keeps it: the house style fills only what is not set.
Review, Copy and mTool all use this one output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from bs4 import BeautifulSoup, Tag

from app.notes.render.css import (
    fill_undeclared_borders_white, merge_cell_style, merge_style, neighbour_declared_sides,
    parse_decls, prop_of, decls, whiteout_hidden_borders,
)
from app.notes.render.tables import (
    WIDTHS_ATTR, amount_columns, apply_column_widths, cells, fit_table_width,
    heading_rows, layout_column_widths, own_rows, should_right_align_cell,
)

# A table html.py marks with the font it needs to fit (blocks `font_pt`).
FONT_SIZE_ATTR = "data-formatter-font-size"
# A table whose source boxes every cell (blocks `frame: grid`).
GRID_ATTR = "data-frame"
MIN_TABLE_FONT_SIZE_PT = 8
HOUSE_CELL_PADDING_PX = (3, 3)


@dataclass(frozen=True)
class NotesTableStyle:
    """What the decorator draws with. The defaults are v1's bordered baseline,
    which its tests pin; `from_house` gives the look the Settings page sets."""
    border_style: str = "single"          # "single" grid or "none"
    font_size_pt: int = 10
    cell_padding_px: tuple[int, int] = (4, 8)
    paragraph_spacing_px: int = 8
    border_color: str | None = None       # None: v1's #999
    header_fill: str | None = "#f3f4f6"
    header_bold: bool = True
    body_align: str = "justify"           # prose with no alignment of its own
    min_font_pt: int = MIN_TABLE_FONT_SIZE_PT


def from_house(house: dict) -> NotesTableStyle:
    """The decorator style for the Settings page's notes house style."""
    return NotesTableStyle(
        border_style="none", font_size_pt=int(house["table_font_pt"]),
        cell_padding_px=HOUSE_CELL_PADDING_PX, paragraph_spacing_px=3, border_color="#000000",
        header_fill=None, header_bold=False,
        body_align="left" if house["body_text"] == "left" else "justify",
        min_font_pt=int(house["smallest_table_font_pt"]),
    )


DEFAULT_STYLE = NotesTableStyle()


def _font_css(o: NotesTableStyle) -> str:
    # Points, not pixels: mTool reads a bare font size in points.
    return f"font-family: Arial, sans-serif; font-size: {o.font_size_pt}pt;"


def _border_css(o: NotesTableStyle) -> str:
    if o.border_style == "none":
        return ""
    return f"border: 0.75px solid {o.border_color or '#999'}; "


def _table_style(gap: int) -> str:
    return f"border-collapse: collapse; margin: {gap}px 0; width: 100%; max-width: 100%; table-layout: fixed;"


def _cell_style_base(o: NotesTableStyle, lite: bool = False) -> str:
    pad_v, pad_h = o.cell_padding_px
    base = f"{_border_css(o)}padding: {pad_v}px {pad_h}px; "
    if not lite:
        # vertical-align does not inherit, so it stays on each cell.
        base += "vertical-align: top; "
    return base


def _table_inherited_css(o: NotesTableStyle, lite: bool = False) -> str:
    """Font and wrapping inherit, so they are said once on the table rather
    than on every cell: about 90 characters a cell against mTool's limit."""
    css = _font_css(o)
    if not lite:
        css += " overflow-wrap: break-word; word-break: break-word;"
    return css


def _header_extra(o: NotesTableStyle) -> str:
    fill = f" background: {o.header_fill};" if o.header_fill else ""
    # <th> is bold by default in most editors, so plain must be said.
    weight = " font-weight: 600;" if o.header_bold else " font-weight: 400;"
    return fill + weight


def _paragraph_style(o: NotesTableStyle) -> str:
    return _font_css(o) + f" margin: 0 0 {o.paragraph_spacing_px}px 0;"


def _heading_style(o: NotesTableStyle) -> str:
    return _font_css(o) + " margin: 12px 0 6px 0; font-weight: 600;"


# A heading cell below the table's heading rows draws as a data cell.
_BODY_TH = " font-weight: 400;"
_KEYWORD_WEIGHTS = {"bold": 700, "bolder": 700, "normal": 400, "lighter": 400}


def _table_font_style(o: NotesTableStyle, el: Tag) -> NotesTableStyle:
    """``o`` with the smaller font a table states for the text inside it.
    It only shrinks, and never below the house minimum."""
    tables = [el] if el.name == "table" else []
    for table in [*tables, *el.find_parents("table")]:
        raw = str(table.get(FONT_SIZE_ATTR, ""))
        if re.fullmatch(r"[0-9]{1,2}", raw):
            size = max(o.min_font_pt, int(raw))
            return o if size >= o.font_size_pt else replace(o, font_size_pt=size)
    return o


def _emphasis_weight(mark: Tag) -> str:
    """Weight for an unstyled <strong>: semibold, unless the nearest ancestor
    that sets a weight is already bold, so emphasis never compounds."""
    for parent in mark.parents:
        raw = parse_decls(parent.get("style", "")).get("font-weight", "")
        value = raw.lower().replace("!important", "").strip()
        if not value or value == "inherit":
            continue
        weight = _KEYWORD_WEIGHTS.get(value) or (int(value) if value.isdigit() else 0)
        return str(weight) if weight >= 600 else "600"
    return "600"


def _has_persisted_indent(el: Tag) -> bool:
    return any(prop_of(d) == "margin-left" for d in decls(el.get("style") or ""))


def _indent_source_heading_levels(soup: BeautifulSoup) -> None:
    """Indent deeper headings and the blocks under them, 2em a level."""
    blocks = [node for node in soup.contents if isinstance(node, Tag)]
    headings = {"h1", "h2", "h3", "h4", "h5", "h6"}
    levels = [int(node.name[1]) for node in blocks if node.name in headings]
    if not levels:
        return
    baseline = min(levels)
    parent = (re.match(r"^\s*(\d+)(?=\s|\.|$)", blocks[0].get_text())
              if blocks[0].name == "h3" else None)
    sub = (re.match(r"^\s*(\d+)(?:\.\d+|\([a-zivx]+\))(?=\s|\.|$)", blocks[1].get_text(), re.I)
           if len(blocks) > 1 and blocks[1].name == "h3" else None)
    adjacent_subnote = bool(parent and sub and parent.group(1) == sub.group(1))
    depth = 0
    for index, node in enumerate(blocks):
        if index > 0 and node.name == "h3" and re.match(r"^\s*\d+[.)]?(?=\s|$)", node.get_text()):
            adjacent_subnote = False
        if node.name in headings:
            depth = max(0, int(node.name[1]) - baseline)
        effective = max(1, depth) if adjacent_subnote and index > 0 else depth
        if (effective and node.name in headings | {"p", "table", "ul", "ol"}
                and not _has_persisted_indent(node)):
            merge_style(node, f"margin-left: {2 * effective}em;")


def _add_transport_breaks(soup: BeautifulSoup) -> None:
    """A real blank paragraph between prose and tables: TX27 ignores CSS
    paragraph margins."""
    blocks = [node for node in soup.children if isinstance(node, Tag)]
    for left, right in zip(blocks, blocks[1:]):
        if left.name in {"p", "table"} and right.name in {"p", "table"}:
            spacer = soup.new_tag("p", attrs={"data-mtool-spacer": "1"})
            spacer["style"] = "margin: 0;"
            spacer.string = "\xa0"
            right.insert_before(spacer)


def _drop_markers(soup: BeautifulSoup) -> None:
    """Our bookkeeping attributes mean nothing to TX and cost characters."""
    for attr in (WIDTHS_ATTR, FONT_SIZE_ATTR, GRID_ATTR):
        for el in soup.find_all(attrs={attr: True}):
            del el[attr]


def add_transport_breaks(html: str) -> str:
    """The flat tier: the plain HTML with only mTool's blank lines added."""
    soup = BeautifulSoup(html, "html.parser")
    _drop_markers(soup)
    _add_transport_breaks(soup)
    return str(soup)


def without_transport_breaks(html: str) -> str:
    """Remove only the exact blank paragraphs added for mTool."""
    soup = BeautifulSoup(html, "html.parser")
    for spacer in soup.select('p[data-mtool-spacer="1"]'):
        if spacer.find(True) is not None or spacer.get_text() != "\xa0":
            raise ValueError("mTool transport spacer contains note content")
        spacer.decompose()
    return str(soup)


def _own_style(style: NotesTableStyle, table: Tag) -> NotesTableStyle:
    """A grid table draws the single grid; every other table draws no grid."""
    if table.get(GRID_ATTR) == "grid":
        return replace(style, border_style="single")
    return style


def _decorate_table(table: Tag, style: NotesTableStyle, lite: bool, compact: bool) -> bool:
    """Table-level styling. Returns whether its cells may be compacted."""
    merge_cell_style(table, "text-align: left;")
    widths = layout_column_widths(table)
    merge_style(table, _table_style(style.paragraph_spacing_px))
    merge_style(table, _table_inherited_css(_table_font_style(style, table), lite=lite))
    # A cell that owns a border decides the grid: a table-level border="1"
    # would redraw over it.
    cells_own_borders = any("border" in (c.get("style") or "") for c in table.find_all(("td", "th")))
    compactable = False
    if style.border_style == "none" or cells_own_borders:
        for attr in ("border", "cellpadding", "cellspacing"):
            if table.has_attr(attr):
                del table[attr]
    else:
        table.attrs.setdefault("border", "1")
        table.attrs.setdefault("cellpadding", "4")
        table.attrs.setdefault("cellspacing", "0")
        compactable = compact and not any("background" in (c.get("style") or "")
                                          for c in table.find_all(("td", "th")))
    if widths is not None:
        apply_column_widths(table, widths)
    else:
        fit_table_width(table)
    return compactable


def _decorate_row(row: Tag, style: NotesTableStyle, lite: bool, compact: bool,
                  amount_cols: set[int], header_row: bool) -> None:
    row_cells = cells(row)
    cell_base = _cell_style_base(style, lite=lite)
    for idx, cell in enumerate(row_cells):
        numeric = (should_right_align_cell(cell.get_text(), idx, len(row_cells))
                   or (header_row and idx > 0 and idx in amount_cols))
        align = " text-align: right;" if numeric else " text-align: left;"
        if compact:
            # Table attributes carry the padding; keep borders and what differs.
            addition = _border_css(style)
            if cell.name == "th" and header_row:
                addition += _header_extra(style).lstrip() + align
            elif cell.name == "th":
                addition += _BODY_TH.lstrip() + align
            elif numeric:
                addition += "text-align: right;"
            if addition:
                merge_cell_style(cell, addition)
        elif cell.name == "th" and header_row:
            merge_cell_style(cell, cell_base + _header_extra(style).lstrip() + align)
        elif cell.name == "th":
            merge_cell_style(cell, cell_base + _BODY_TH + align)
        else:
            merge_cell_style(cell, cell_base + align)


def decorate_notes_html(html: str, style: NotesTableStyle = DEFAULT_STYLE,
                        lite: bool = False, compact: bool = False,
                        fill_white_grid: bool = True) -> str:
    """The note's HTML with mTool's inline styling, wrapped in a font-bearing
    ``<div>``. Pure: the input is not changed.

    ``compact`` lets table attributes carry the padding of a gridded table;
    ``lite`` drops vertical alignment and wrapping hints; ``fill_white_grid``
    paints every undeclared edge of an ungridded table white so mTool shows
    no grey grid. The size tiers in fit.py step through these."""
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    styles = {id(t): _own_style(style, t) for t in tables}
    compact_tables = {id(t) for t in tables if _decorate_table(t, styles[id(t)], lite, compact)}

    for table in tables:
        own = styles[id(table)]
        amount_cols = amount_columns(table)
        headers = heading_rows(table)
        for row in own_rows(table):
            _decorate_row(row, own, lite, id(table) in compact_tables, amount_cols, id(row) in headers)

    # mTool draws hidden and undeclared edges grey: spell them out white.
    for table in tables:
        own_cells = [el for el in table.find_all(("td", "th")) if el.find_parent("table") is table]
        for el in own_cells:
            whiteout_hidden_borders(el)
        if fill_white_grid and styles[id(table)].border_style == "none":
            skip = neighbour_declared_sides([c for c in (cells(r) for r in own_rows(table)) if c])
            for el in own_cells:
                fill_undeclared_borders_white(el, skip.get(id(el), frozenset()))
        whiteout_hidden_borders(table)

    _indent_source_heading_levels(soup)
    for p in soup.find_all("p"):
        own = _table_font_style(style, p)
        if _has_persisted_indent(p):
            merge_style(p, _font_css(own) + " margin-top: 0; margin-right: 0; "
                        f"margin-bottom: {style.paragraph_spacing_px}px;")
        else:
            merge_style(p, _paragraph_style(own))
    for h in soup.find_all(("h1", "h2", "h3", "h4", "h5", "h6")):
        own = _table_font_style(style, h)
        if h.find_parent(("td", "th")) is None:
            merge_cell_style(h, "text-align: left;")
        if _has_persisted_indent(h):
            merge_style(h, _font_css(own) + " margin-top: 12px; margin-right: 0; "
                        "margin-bottom: 6px; font-weight: 600;")
        else:
            merge_style(h, _heading_style(own))
    for mark in soup.find_all(("strong", "b")):
        if "font-weight" not in parse_decls(mark.get("style", "")):
            merge_style(mark, f"font-weight: {_emphasis_weight(mark)};")
    for lst in soup.find_all(("ul", "ol", "li")):
        merge_style(lst, _font_css(_table_font_style(style, lst)))

    _drop_markers(soup)
    _add_transport_breaks(soup)

    # The font on a wrapper, so text nothing else styles still inherits it.
    wrapper = soup.new_tag("div")
    wrapper["style"] = _font_css(style) + f" text-align: {style.body_align};"
    for node in list(soup.contents):
        wrapper.append(node.extract())
    return str(wrapper)

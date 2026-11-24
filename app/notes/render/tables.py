"""Table helpers for the mTool decorator: amount cells, heading rows and
column widths in the dialect mTool's editor reads.

Copied from v1's `mtool/notes_decorate.py` (lines 24-81 and 568-728), less
the editor-resize and merged-cell paths: v2 tables have no spans (they are
split when a note is made) and no editor resizes them.
"""
from __future__ import annotations

import re

from bs4 import Tag

from app.notes.render.css import decls

# Accountant amounts: `1,595`, `(95)`, a bare dash for an empty year, decimals.
_NUMERIC_CELL_RE = re.compile(r"^\(?\s*-?\s*[\d,]+(?:\.\d+)?\s*\)?$|^[-—–]+$")

# The column widths html.py writes, one `<col style="width: Npx">` per column.
WIDTHS_ATTR = "data-formatter-widths"


def is_numeric_cell_text(text: str) -> bool:
    return bool(_NUMERIC_CELL_RE.match(text.strip()))


def should_right_align_cell(text: str, index: int, cells_in_row: int, colspan: int = 1) -> bool:
    """Amounts align right, except the first cell of a multi-column row: the
    row label stays left even when it reads like a number (a "2024" label)."""
    if index == 0 and (cells_in_row > 1 or colspan > 1):
        return False
    return is_numeric_cell_text(text)


def cells(row: Tag) -> list[Tag]:
    return [c for c in row.children if isinstance(c, Tag) and c.name in ("td", "th")]


def own_rows(table: Tag) -> list[Tag]:
    """The table's own rows; a nested table's rows are its own."""
    return [r for r in table.find_all("tr") if r.find_parent("table") is table]


def heading_rows(table: Tag) -> set[int]:
    """``id()`` of the leading heading rows: thead rows, or all-``th`` rows
    before the first row holding a data cell. A ``th`` further down labels
    its row and draws like a data cell."""
    ids: set[int] = set()
    for row in own_rows(table):
        row_cells = cells(row)
        if row.parent.name == "thead" or (row_cells and all(c.name == "th" for c in row_cells)):
            ids.add(id(row))
            continue
        break
    return ids


def amount_columns(table: Tag) -> set[int]:
    columns: set[int] = set()
    for row in own_rows(table):
        row_cells = cells(row)
        if len(row_cells) < 2:
            continue
        columns.update(i for i, c in enumerate(row_cells)
                       if i > 0 and is_numeric_cell_text(c.get_text()))
    return columns


def fit_table_width(table: Tag) -> None:
    """Make the table fill mTool's page. TX ignores CSS widths, so this uses
    the legacy ``width`` attributes: 100% on the table and, for an accountant
    table (trailing columns mostly amounts), percent shares on the first full
    row. Text tables keep their natural columns."""
    per_row = [cells(r) for r in own_rows(table)]
    counts = [len(c) for c in per_row if c]
    if not counts:
        return
    table["width"] = "100%"
    ncols = max(counts)
    if ncols < 2:
        return
    first_full = next((c for c in per_row if len(c) == ncols), None)
    if first_full is None:
        return
    trailing = [c.get_text().strip() for row in per_row for c in row[1:]]
    non_empty = [t for t in trailing if t]
    numeric = sum(1 for t in non_empty if is_numeric_cell_text(t))
    if not non_empty or numeric * 2 <= len(non_empty):
        return
    # Amount columns share a bounded slice; the label keeps the rest, at
    # least 30%. With nine or more columns that cannot hold: page fit only.
    share = min(18, max(10, 70 // (ncols - 1)))
    label = 100 - share * (ncols - 1)
    if label < 30:
        return
    for i, cell in enumerate(first_full):
        cell["width"] = f"{label}%" if i == 0 else f"{share}%"


def layout_column_widths(table: Tag) -> list[int] | None:
    """Pixel widths from the marked ``<colgroup>``, one per grid column."""
    groups = [g for g in table.find_all("colgroup", recursive=False)
              if g.get(WIDTHS_ATTR) == "true"]
    if len(groups) != 1:
        return None
    widths = []
    for col in groups[0].find_all("col"):
        found = [int(m.group(1)) for m in (re.fullmatch(r"width:\s*(\d+)px", d, re.I)
                                           for d in decls(col.get("style") or "")) if m]
        if len(found) != 1 or found[0] <= 0:
            return None
        widths.append(found[0])
    grid = max((len(cells(r)) for r in own_rows(table)), default=0)
    return widths if widths and len(widths) == grid else None


def percent_shares(widths: list[int]) -> list[int]:
    """Whole-percent shares in proportion, at least 1% each."""
    total = sum(widths)
    shares = [max(1, round(w * 100 / total)) for w in widths]
    shares[shares.index(max(shares))] += 100 - sum(shares)
    return shares


def apply_column_widths(table: Tag, widths: list[int]) -> None:
    """Stated column widths as percent ``width`` attributes on the first row
    that has every column, and the table at the page width."""
    if not table.has_attr("width"):
        table["width"] = "100%"
    shares = percent_shares(widths)
    for row in own_rows(table):
        row_cells = cells(row)
        if len(row_cells) == len(widths):
            for cell, share in zip(row_cells, shares):
                cell["width"] = f"{share}%"
            return

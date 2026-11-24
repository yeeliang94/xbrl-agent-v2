"""How a genuine mTool workbook lays out its columns, read from its own markers.

Copied from v1 `mtool/column_detect.py` (`_marker_rows`, `entity_scope_rows`,
`category_domain_rows`, `_semantic_layout`) and v1 `mtool/template_map.py`
(`index_workbook`, `_dimensional_period_blocks`, `_block_for_primary_row`).
Standard library only.

An mTool sheet marks its own structure:

- `#PRIM#` the label column, `#ENDT#` each value column's period end date,
- `#DOM#` a row of category members (share classes, equity components) or,
  beside the consolidation axis, which columns are Group and which Company.

So this year and last year are told apart by comparing dates, never by
which column comes first. A sheet without `#PRIM#` has no mTool layout.

Not copied: the positional fallback for marker-less workbooks (a person's
workbook is read by meaning only), the fingerprint registry, the operator
confirmation forms and the reporting-period checks against the report.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.workbook.xlsx_cells import Cells, taxonomy_ids

MARKER_LABEL = "#PRIM#"
MARKER_END_DATE = "#ENDT#"
MARKER_DIMENSION = "#DOM#"
_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

Occurrences = dict[str, list[tuple[str, int, str]]]


def _parse_date(text: str) -> tuple[int, int, int] | None:
    m = _DATE.fullmatch((text or "").strip())
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    return year, month, day


def marker_rows(cells: Cells) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for row, row_cells in cells.items():
        for _kind, text in row_cells.values():
            value = (text or "").strip()
            if value.startswith("#") and value.endswith("#"):
                found.setdefault(value, []).append(row)
    return {k: sorted(set(v)) for k, v in found.items()}


def entity_scope_rows(cells: Cells) -> dict[int, dict[str, str]]:
    """{row: {column: "Group" | "Company"}} from the native consolidation markers."""
    scopes = {}
    for row in marker_rows(cells).get(MARKER_DIMENSION, []):
        if not any(re.search(r"\.xsd#(?:ifrs-full|ifrs-smes)_ConsolidatedAndSeparateFinancialStatementsAxis(?:$|:)",
                             raw or "") for _, raw in cells[row].values()):
            continue
        columns = {col: {"Consolidated": "Group", "Separate": "Company"}[raw]
                   for col, (_, raw) in cells[row].items() if raw in {"Consolidated", "Separate"}}
        if columns:
            scopes[row] = columns
    return scopes


def category_domain_rows(cells: Cells) -> list[int]:
    """Category marker rows. Leaves out entity-scope rows and restatement metadata."""
    rows = []
    scope_rows = entity_scope_rows(cells)
    for row in marker_rows(cells).get(MARKER_DIMENSION, []):
        if row in scope_rows:
            continue
        values = {(text or "").strip() for _kind, text in cells[row].values()}
        if "abc::abc" in values and values <= {"", "#DOM#", "abc::abc", "Restated"}:
            continue
        rows.append(row)
    return rows


@dataclass
class SheetLayout:
    """One mTool sheet: its label column and, for an ordinary sheet, which
    column holds each (entity, period). A category sheet's columns are
    chosen per figure from its taxonomy category instead."""
    label_column: str | None
    dimensional: bool
    columns: dict[tuple[str, str], str] = field(default_factory=dict)   # (entity, "CY"|"PY") -> column
    unresolved: list[str] = field(default_factory=list)                  # one sentence per problem


def sheet_layout(cells: Cells, *, group: bool) -> SheetLayout | None:
    """The sheet's layout from its markers, or None when it has no `#PRIM#` marker."""
    markers = marker_rows(cells)
    if MARKER_LABEL not in markers:
        return None
    label_col = next((col for row in markers[MARKER_LABEL] for col, (_, text) in cells.get(row, {}).items()
                      if (text or "").strip() == MARKER_LABEL), None)
    dimensional = bool(category_domain_rows(cells))
    layout = SheetLayout(label_col, dimensional)
    if dimensional:
        return layout
    dates: dict[str, set] = defaultdict(set)
    for row in markers.get(MARKER_END_DATE, []):
        for col, (_kind, text) in cells.get(row, {}).items():
            if (parsed := _parse_date(text)) is not None:
                dates[col].add(parsed)
    conflicting = sorted(col for col, found in dates.items() if len(found) > 1)
    if conflicting:
        layout.unresolved.append(f"Column {', '.join(conflicting)} has two reporting dates.")
        return layout
    ordered = sorted({next(iter(d)) for d in dates.values()}, reverse=True)
    period_of = {col: "CY" if next(iter(d)) == ordered[0] else "PY" if len(ordered) > 1
                 and next(iter(d)) == ordered[1] else None for col, d in dates.items()}
    scope_rows = entity_scope_rows(cells)
    by_column: dict[str, set[str]] = defaultdict(set)
    for scopes in scope_rows.values():
        for col, scope in scopes.items():
            by_column[col].add(scope)
    entities = ("Group", "Company") if group else ("Company",)
    for entity in entities:
        for period in ("CY", "PY"):
            if scope_rows:
                matches = [c for c, p in period_of.items() if p == period and by_column.get(c) == {entity}]
            elif group:
                matches = []   # a Group sheet must say which columns are Group (v1, Step 10)
            else:
                matches = [c for c, p in period_of.items() if p == period]
            if len(matches) == 1:
                layout.columns[(entity, period)] = matches[0]
            else:
                layout.unresolved.append(f"No single column is marked for the {entity}, "
                                         f"{'this year' if period == 'CY' else 'last year'}.")
    return layout


def period_blocks(cells: Cells) -> list[dict]:
    """A category sheet repeats its rows per period: one block per `#DOM#` row,
    classed this year or last year by the `#ENDT#` dates under it."""
    dom_rows = category_domain_rows(cells)
    scopes = entity_scope_rows(cells)
    end_rows = marker_rows(cells).get(MARKER_END_DATE, [])
    blocks = []
    for index, dom_row in enumerate(dom_rows):
        next_dom = dom_rows[index + 1] if index + 1 < len(dom_rows) else None
        column_dates: dict[str, set] = defaultdict(set)
        for row in end_rows:
            if row >= dom_row and (next_dom is None or row < next_dom):
                for col, (_kind, raw) in cells.get(row, {}).items():
                    if (parsed := _parse_date(raw)) is not None:
                        column_dates[col].add(parsed)
        earlier = [r for r in scopes if r <= dom_row]
        blocks.append({"dom_row": dom_row, "previous_dom_row": dom_rows[index - 1] if index else None,
                       "next_dom_row": next_dom, "column_dates": dict(column_dates),
                       "entity_scopes": scopes[max(earlier)] if earlier else {}})
    ordered = sorted({d for b in blocks for dates in b["column_dates"].values() for d in dates}, reverse=True)
    for block in blocks:
        block["column_periods"] = {
            col: ("CY" if next(iter(dates)) == ordered[0]
                  else "PY" if len(ordered) > 1 and next(iter(dates)) == ordered[1] else None)
            for col, dates in block["column_dates"].items() if len(dates) == 1}
        block["periods"] = set(block["column_periods"].values()) - {None}
    return blocks


def block_for_row(blocks: list[dict], row: int) -> dict | None:
    candidates = [b for b in blocks if b["dom_row"] <= row]
    if not candidates:
        return None
    block = candidates[-1]
    return block if block["next_dom_row"] is None or row < block["next_dom_row"] else None


_TOTAL_MARKERS = {"0:::abc::abc::abc", "0:::0", "0:::0:::abc::abc::abc"}
_SEPARATE_TOTAL = re.compile(
    r"0::[A-Za-z0-9_.-]+\.xsd#ifrs-(?:full|smes)_ConsolidatedAndSeparateFinancialStatementsAxis"
    r"::[A-Za-z0-9_.-]+\.xsd#ifrs-(?:full|smes)_SeparateMember:::0(?::::abc::abc::abc)?")
_CATEGORY_TOTALS = (
    ("DisclosureOfClassesOfShareCapitalTable", "ClassesOfShareCapitalAxis", "ClassesOfShareCapitalMember"),
    ("DisclosureOfTransactionsBetweenRelatedPartiesTable", "CategoriesOfRelatedPartiesAxis",
     "EntitysTotalForRelatedPartiesMember"),
)


def index_taxonomy(cells_by_sheet: dict[str, Cells]) -> Occurrences:
    """Where each SSM element and category member appears: {id: [(sheet, row, column)]}.

    Only the closed `<file>.xsd#<id>` syntax is indexed, never arbitrary text.
    mTool marks an all-components (equity) or all-categories total column
    with a zero beside its table and axis headers and the label Total; that
    column is indexed as the aggregate member, never inferred from position."""
    occurrences: Occurrences = defaultdict(list)
    for sheet, cells in cells_by_sheet.items():
        for row, row_cells in cells.items():
            for col, (_kind, raw) in row_cells.items():
                for identifier in taxonomy_ids(raw or ""):
                    occurrences[identifier].append((sheet, int(row), col))
        category_rows = category_domain_rows(cells)
        for row, row_cells in cells.items():
            ids = [set(taxonomy_ids(raw or "")) for _, raw in row_cells.values()]
            members = []
            for prefix in ("ifrs-full", "ifrs-smes"):
                if any({f"{prefix}_StatementOfChangesInEquityTable", f"{prefix}_ComponentsOfEquityAxis"} <= s
                       for s in ids):
                    members.append(f"{prefix}_EquityMember")
                for table, axis, member in _CATEGORY_TOTALS:
                    if any({f"{prefix}_{table}", f"{prefix}_{axis}"} <= s for s in ids):
                        members.append(f"{prefix}_{member}")
            if not members:
                continue
            next_category = next((r for r in category_rows if r > row), None)
            label_rows = [row + 2] + ([next_category] if next_category else [])
            for col, (kind, raw) in row_cells.items():
                marked = (kind == "N" and raw == "0") or (
                    kind == "S" and (raw in _TOTAL_MARKERS or bool(_SEPARATE_TOTAL.fullmatch(raw or ""))))
                if marked and any(cells.get(r, {}).get(col, (None, ""))[1] == "Total" for r in label_rows):
                    for member in members:
                        occurrences[member].append((sheet, int(row), col))
    return dict(occurrences)


def has_taxonomy_names(cells_by_sheet: dict[str, Cells]) -> bool:
    return any(taxonomy_ids(raw) for cells in cells_by_sheet.values()
               for row in cells.values() for _, raw in row.values())

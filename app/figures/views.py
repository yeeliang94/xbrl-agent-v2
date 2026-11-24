"""One statement of a run, laid out for the review screen, in two orders.

- Report order: the lines as the report prints them (by page and order on
  the page), each with the template field it was saved in.
- Template order: every template line in template order, face sheet first,
  including lines with no figure.

Each row carries what the review grid draws (see the prototype's `grid()`):
the printed label, the field label, a cell per column, the page, the
certainty and reason, whether a person edited it, and the row's status.
Figures are read through the figure store.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from app.catalog import lookup
from app.catalog.statements import StatementType
from app.checks.framework import DEFAULT_TOLERANCE
from app.checks.runner import read_checks
from app.figures import store
from app.figures.sums import add_up
from app.starting import comparatives

_PERIOD_WORDS = {"CY": "This year", "PY": "Last year"}


class ViewError(ValueError):
    """A statement that cannot be shown. `str()` is one plain sentence."""


class StatementNotInRun(ViewError):
    """The statement is not one of the run's statements."""


def _columns(family: lookup.RunFamily) -> list[dict]:
    return [{"key": f"{scope}:{period}", "entity_scope": scope, "period": period, "matrix_col": None,
             "label": (f"{scope}, {_PERIOD_WORDS[period].lower()}" if family.level == "group"
                       else _PERIOD_WORDS[period])}
            for scope in family.entity_scopes for period in family.periods]


def _cell(figure: Optional[dict], concept: lookup.Concept, printed: Optional[float] = None) -> dict:
    writable = not (figure and figure["locked"]) and (
        (concept.writable and not concept.is_total)
        or bool(figure and figure["children_status"] == "aggregate_only"))
    return {
        "figure_id": figure["id"] if figure else None,
        "concept_uuid": concept.concept_uuid,
        "value": figure["value"] if figure else None,
        "printed": printed,
        "stated": figure["stated_value"] if figure else None,
        "certainty": figure["certainty"] if figure else "sure",
        "reason": figure["reason"] if figure else "",
        "edited": bool(figure and figure["person_edited"]),
        "origin": figure["origin"] if figure else None,
        "writable": writable,
        "agent_writable": writable and not (figure and figure["origin"] == "typed_in_workbook"),
        "lines_sum": figure.get("lines_sum") if figure else None,
        # A last-year figure kept from the starting workbook: the report's comparative as the agent read
        # it, and whether only its sign differs (step 10e). A person settles a sign question.
        "sign_question": bool(figure and figure["sign_question"]),
        "comparison": figure.get("comparison") if figure else None,
    }


def _differs(cell: dict) -> bool:
    """A total as the report gives it (printed, or with no breakdown) that its lines do not add up to."""
    if cell["stated"] is not None and (cell["value"] is None
                                       or abs(cell["stated"] - cell["value"]) > DEFAULT_TOLERANCE):
        return True
    return cell["lines_sum"] is not None and cell["value"] is not None and \
        abs(cell["lines_sum"] - cell["value"]) > DEFAULT_TOLERANCE


def _status(cells: list[dict], failing: set[str]) -> Optional[str]:
    if any(c["concept_uuid"] in failing for c in cells):
        return "does_not_tally"
    if any(_differs(c) for c in cells):
        return "differs_from_report"
    if any(c["figure_id"] and c["certainty"] == "unsure" for c in cells):
        return "unsure"
    if any(c["edited"] for c in cells):
        return "edited"
    return None


def _row(kind: str, label: str, field_label: str, cells: dict[str, dict], failing: set[str], **extra) -> dict:
    present = [c for c in cells.values() if c["figure_id"]]
    unsure = next((c for c in present if c["certainty"] == "unsure"), None)
    return {
        "kind": kind, "label": label, "field_label": field_label, "cells": cells,
        "status": _status(list(cells.values()), failing),
        "certainty": "unsure" if unsure else "sure",
        "reason": (unsure or (present[0] if present else {"reason": ""}))["reason"],
        "edited": any(c["edited"] for c in present),
        **extra,
    }


def _sheet_rank(sheet: str) -> tuple[bool, str]:
    low = sheet.lower()
    return ("sub" in low or "analysis" in low, low)


def _figures_by_key(conn: sqlite3.Connection, run_id: int, template_id: str,
                    uuids: set[str]) -> dict[tuple, dict]:
    """The template's figures. A total with no breakdown also carries what
    the lines saved under it add up to, as `lines_sum`."""
    figures = {(f["concept_uuid"], f["entity_scope"], f["period"]): f
               for f in store.run_figures(conn, run_id)
               if f["concept_uuid"] in uuids and f["dimension_key"] == ""}
    edges = lookup.edges_for(conn, {template_id})
    compared = comparatives.by_figure(conn, run_id)
    for (uuid, scope, period), figure in figures.items():
        figure["comparison"] = compared.get(figure["id"])
        if figure["children_status"] == "aggregate_only":
            figure["lines_sum"] = add_up(edges.get(uuid, []), lambda child, s=scope, p=period: (
                figures.get((child, s, p)) or {}).get("value"))
    return figures


def statement_view(conn: sqlite3.Connection, run_id: int, statement: str, order: str) -> dict:
    family = lookup.run_family(conn, run_id)
    if family is None:
        raise ViewError("There is no such run.")
    try:
        stmt = StatementType(statement)
    except ValueError as exc:
        raise ViewError("The statement is SOFP, SOPL, SOCI, SOCF or SOCIE.") from exc
    if order not in ("report", "template"):
        raise ViewError("The order is report or template.")
    template_id = family.template_ids.get(stmt)
    if template_id is None:
        raise StatementNotInRun(f"{stmt.value} is not part of this run.")
    concepts = {c.concept_uuid: c for c in lookup.template_concepts(conn, template_id)}
    figures = _figures_by_key(conn, run_id, template_id, set(concepts))
    failing = {c["target_concept_uuid"] for c in read_checks(conn, run_id)
               if c["status"] == "failed" and c["target_concept_uuid"]}
    matrix = any(c.matrix_col for c in concepts.values())
    if matrix:
        columns, rows = _matrix(family, concepts, figures, failing, order)
    elif order == "template":
        columns, rows = _columns(family), _template_rows(conn, family, template_id, concepts, figures, failing)
    else:
        columns, rows = _columns(family), _report_rows(family, concepts, figures, failing)
    return {"run_id": run_id, "statement": stmt.value, "variant": family.variants.get(stmt),
            "template_id": template_id, "order": order, "columns": columns, "rows": rows}


def _template_rows(conn, family, template_id, concepts, figures, failing) -> list[dict]:
    """Every physical template row, including face rows that show a sub-sheet total."""
    rows = []
    slots = conn.execute(
        "SELECT sheet, row, label, canonical_target_id FROM template_slots WHERE template_id = ?",
        (template_id,)).fetchall()
    for slot in sorted(slots, key=lambda s: (_sheet_rank(s["sheet"]), s["row"])):
        concept = concepts.get(slot["canonical_target_id"])
        if concept is None:
            continue
        label = slot["label"].lstrip("*").strip()
        position = {"concept_uuid": concept.concept_uuid, "sheet": slot["sheet"], "row": slot["row"]}
        if concept.kind == "ABSTRACT":
            rows.append(_row("heading", label, label, {}, failing, **position, page=None, printed_label=None))
            continue
        cells, page, printed_label = {}, None, None
        for col in _columns(family):
            figure = figures.get((concept.concept_uuid, col["entity_scope"], col["period"]))
            cells[col["key"]] = _cell(figure, concept)
            if figure and figure["lines"] and page is None:
                page, printed_label = figure["lines"][0]["page"], figure["lines"][0]["printed_label"]
        rows.append(_row("total" if concept.is_total else "line", label, label, cells, failing,
                         **position, page=page, printed_label=printed_label))
    return rows


def _report_rows(family, concepts, figures, failing) -> list[dict]:
    """One row per printed line, in the order the report prints them."""
    grouped: dict[tuple, dict] = {}
    for (uuid, scope, period), figure in figures.items():
        concept = concepts[uuid]
        for line in figure["lines"]:
            key = (line["page"], line["print_order"], line["printed_label"], uuid)
            entry = grouped.setdefault(key, {"concept": concept, "section": line["section"], "cells": {}})
            entry["cells"][f"{scope}:{period}"] = _cell(figure, concept, line["amount"])
    rows, section = [], None
    for (page, print_order, printed_label, _uuid), entry in sorted(grouped.items()):
        if entry["section"] and entry["section"] != section:
            section = entry["section"]
            rows.append(_row("heading", section, section, {}, failing, concept_uuid=None, sheet=None, row=None,
                             page=page, print_order=None, printed_label=section))
        concept = entry["concept"]
        cells = {col["key"]: entry["cells"].get(col["key"]) or _cell(
            figures.get((concept.concept_uuid, col["entity_scope"], col["period"])), concept)
            for col in _columns(family)}
        rows.append(_row("total" if concept.is_total else "line", printed_label, concept.plain_label, cells,
                         failing, concept_uuid=concept.concept_uuid, sheet=concept.sheet, row=concept.row,
                         page=page, print_order=print_order, printed_label=printed_label))
    return rows


def _matrix(family, concepts, figures, failing, order) -> tuple[list[dict], list[dict]]:
    """The equity statement: one block of rows per entity and period, a column per component."""
    cols = sorted({(c.matrix_col, c.matrix_col_label) for c in concepts.values() if c.matrix_col},
                  key=lambda c: (len(c[0]), c[0]))
    used = {concepts[uuid].matrix_col for (uuid, _s, _p) in figures if concepts[uuid].matrix_col}
    if order == "report":
        cols = [c for c in cols if c[0] in used]
    columns = [{"key": col, "entity_scope": None, "period": None, "matrix_col": col, "label": label}
               for col, label in cols]
    by_row: dict[int, list[lookup.Concept]] = {}
    for c in concepts.values():
        by_row.setdefault(c.row, []).append(c)
    rows = []
    for scope in family.entity_scopes:
        for period in family.periods:
            title = f"{scope}, {_PERIOD_WORDS[period].lower()}" if family.level == "group" else _PERIOD_WORDS[period]
            block = []
            for row_number in sorted(by_row):
                members = {c.matrix_col: c for c in by_row[row_number]}
                first = by_row[row_number][0]
                if first.kind == "ABSTRACT":
                    if order == "template":
                        block.append(_row("heading", first.plain_label, first.plain_label, {}, failing,
                                          concept_uuid=first.concept_uuid, sheet=first.sheet, row=row_number,
                                          page=None, entity_scope=scope, period=period, printed_label=None))
                    continue
                cells, printed, page, print_order = {}, None, None, None
                for col in columns:
                    concept = members.get(col["matrix_col"])
                    if concept is None:
                        continue
                    figure = figures.get((concept.concept_uuid, scope, period))
                    line = figure["lines"][0] if figure and figure["lines"] else None
                    cells[col["key"]] = _cell(figure, concept, line["amount"] if line else None)
                    if line and printed is None:
                        printed, page, print_order = line["printed_label"], line["page"], line["print_order"]
                if order == "report" and printed is None:
                    continue
                # A grid row is a total when its first component is added up (the Total
                # column is a formula on every row).
                leading = members[min(members, key=lambda col: (len(col), col))]
                block.append(_row("total" if leading.is_total else "line",
                                  printed if order == "report" else first.plain_label, first.plain_label, cells,
                                  failing, concept_uuid=None, sheet=first.sheet, row=row_number, page=page,
                                  print_order=print_order, entity_scope=scope, period=period,
                                  printed_label=printed))
            if order == "report":
                if not block:
                    continue
                block.sort(key=lambda r: (r["page"] or 0, r["print_order"] or 0))
            rows.append(_row("heading", title, title, {}, failing, concept_uuid=None, sheet=None, row=None,
                             page=None, entity_scope=scope, period=period, printed_label=None))
            rows.extend(block)
    return columns, rows

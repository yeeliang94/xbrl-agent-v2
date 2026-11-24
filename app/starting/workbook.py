"""Read a starting workbook: what it says of itself, whether it fits the run,
and which of its figures to import.

Rebuilt from v1 `concept_model/prior_year.py` (`inspect_workbook`,
`_prior_year_inputs`). The cells are read by meaning through the scoring
reader (`app/scoring/workbook_read.read_filled_workbook`), the same reader
and cell map the mTool fill uses, so a figure is imported from the very cell
the fill will later leave alone. Nothing here writes.

Only a genuine mTool workbook is accepted: the fill writes into this same
file (step 10g), and the fill writes mTool workbooks only. Its Filing
Information sheet says its standard, level, unit and year end, read by SSM
name, never by position.

What is planned for import:

- every last-year figure the workbook holds, as `prior_workbook` (locked);
- every this-year figure a person typed, as `typed_in_workbook` (kept fixed,
  the owner's decision of 18 November 2026; v1 overwrote them);
- a total typed over the template's formula, as a total with no breakdown,
  so it keeps its amount and the printed-totals check shows any
  disagreement with its lines (v1 kept these as `aggregate_only` too).

A blank cell is never imported, so it is never zero; a typed 0 or dash is
imported as 0. A total left to its formula is not imported: the template
works it out. A formula a person put in this year's input cell is left
alone and listed: it was not typed. Last year's input formulas are imported
with their worked-out value, as v1 did.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional

from app.catalog.fields import run_fields
from app.catalog.lookup import RunFamily
from app.scope.fields import statement_words
from app.scoring.workbook_read import NothingMatches, read_filled_workbook
from app.workbook.mtool_layout import has_taxonomy_names
from app.workbook.xlsx_cells import Cells, col_to_idx, read_workbook, resolve_sheet_name, split_ref, \
    taxonomy_ids

Key = tuple[str, str, str, str]   # concept_uuid, period, entity_scope, dimension_key

UNIT_WORDS = {"RM": "RM", "RM'000": "RM'000 (thousands)"}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


class Refused(ValueError):
    """The workbook does not fit the run. `str()` is one plain sentence."""


@dataclass
class Planned:
    key: Key
    value: float
    origin: str            # prior_workbook | typed_in_workbook
    total: bool            # a total typed over its formula: imported with no breakdown
    cell: str              # Sheet!E25


@dataclass
class Plan:
    figures: list[Planned] = field(default_factory=list)
    not_imported: list[dict] = field(default_factory=list)   # {"cell", "sentence"}: held something, not read
    formulas_left: list[str] = field(default_factory=list)   # this year's input cells holding a formula
    loose: list[dict] = field(default_factory=list)          # numbers no field of the run claims


# What the workbook says of itself ------------------------------------------

def _filing_value(cells_by_sheet: dict[str, Cells], element: str) -> Optional[str]:
    """The value typed beside an SSM name: the first text after the name's own label."""
    for cells in cells_by_sheet.values():
        for row_cells in cells.values():
            texts = sorted(((col_to_idx(c), str(t or "").strip()) for c, (_k, t) in row_cells.items()),
                           key=lambda pair: pair[0])
            at = next((i for i, (_c, t) in enumerate(texts)
                       if any(e.endswith("_" + element) for e in taxonomy_ids(t))), None)
            if at is None:
                continue
            after = [t for _c, t in texts[at + 1:] if t]
            if len(after) > 1:   # the name's own label, then the value; else look on the next sheet
                return after[1]
    return None


def _iso(text: Optional[str]) -> Optional[str]:
    """A date as the Filing Information sheet holds it: typed as day/month/year, as a date (Excel's day
    number), or as year-month-day. None when it is none of these."""
    text = (text or "").strip()
    try:
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ][\d:.]*)?", text):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        if re.fullmatch(r"\d{4,6}(?:\.0+)?", text):   # Excel's day number: day 1 is 1 January 1900
            return (date(1899, 12, 30) + timedelta(days=int(float(text)))).isoformat()
    except ValueError:
        return None
    return None


def date_words(iso: str) -> str:
    year, month, day = (int(p) for p in iso.split("-"))
    return f"{day} {_MONTHS[month - 1]} {year}"


def facts(cells_by_sheet: dict[str, Cells]) -> dict:
    """{"standard", "level", "unit", "year_end"} as the Filing Information sheet gives them, each None when
    it says nothing this code knows."""
    submission = (_filing_value(cells_by_sheet, "TypeOfSubmission") or "").upper()
    nature = (_filing_value(cells_by_sheet, "NatureOfFinancialStatements") or "").lower()
    rounding = (_filing_value(cells_by_sheet, "LevelOfRoundingUsedInFinancialStatements") or "").lower()
    return {
        "standard": "MPERS" if "MPERS" in submission else "MFRS" if "MFRS" in submission else None,
        "level": "Group" if "consolidated" in nature else "Company" if "separate" in nature else None,
        "unit": "RM" if "actual" in rounding else "RM'000" if "thousand" in rounding else None,
        "year_end": _iso(_filing_value(cells_by_sheet, "CompanyCurrentFinancialYearEndDate")),
    }


def read_cells(path: str) -> dict[str, Cells]:
    """The workbook's cells, refusing anything that is not an mTool workbook.
    Raises `xlsx_cells.WorkbookUnreadable` or `Refused`."""
    _data, cells = read_workbook(path)
    if not has_taxonomy_names(cells):
        raise Refused("This is not an mTool workbook, so attach last year's mTool file rolled forward to "
                      "this year.")
    return cells


# Does it fit the run? -------------------------------------------------------

def _check_fit(family: RunFamily, setup: dict, said: dict, cells: dict[str, Cells], fields: dict) -> None:
    if family.first_statements:
        raise Refused("These are the company's first financial statements, so there is no last year's "
                      "workbook to start from.")
    standard, level = family.standard.upper(), "Group" if family.level == "group" else "Company"
    if said["standard"] and said["standard"] != standard:
        raise Refused(f"The workbook is an {said['standard']} filing but this run files {standard}, so attach "
                      "a workbook for the same standard.")
    if said["level"] and said["level"] != level:
        raise Refused(f"The workbook is a {said['level']} filing but this run is a {level} filing, so attach "
                      "a workbook for the same level.")
    unit = setup.get("unit") or "RM"
    if said["unit"] is None:
        raise Refused("The workbook does not say its level of rounding, so its unit cannot be checked against "
                      "the report; set it in the workbook's filing information.")
    if said["unit"] != unit:
        raise Refused(f"The workbook is in {UNIT_WORDS.get(said['unit'], said['unit'])} but the report is in "
                      f"{UNIT_WORDS.get(unit, unit)}, so attach a workbook in the same unit.")
    year_end = setup.get("year_end")
    if said["year_end"] is None:
        raise Refused("The workbook does not say its year end, so it cannot be checked against the report; "
                      "set it in the workbook's filing information.")
    if year_end and said["year_end"] != year_end:
        raise Refused(f"The workbook is set for the year ending {date_words(said['year_end'])} but the report's "
                      f"year ends {date_words(year_end)}, so roll the workbook forward to this year in mTool "
                      "first.")
    for statement, template_id in family.template_ids.items():
        sheets = {f.sheet for f in fields.values() if f.template_id == template_id}
        if not any(resolve_sheet_name(sheet, cells) for sheet in sheets):
            words = statement_words(statement, family.variants.get(statement))
            raise Refused(f"The workbook has no sheet for the {words} in the {family.variants.get(statement)} "
                          "layout this run uses, so attach a workbook made for the same layouts.")


def check_fit(conn, family: RunFamily, path: str, setup: dict) -> dict[str, Cells]:
    """Refuse (`Refused`, one sentence) a workbook that does not fit the run's setup: its standard, level,
    unit, year end and layouts. `setup` holds the run's `unit` and `year_end`. Returns the workbook's cells.
    The import checks this at the confirm, and the fill again before it writes (step 10g)."""
    cells = read_cells(path)
    _check_fit(family, setup, facts(cells), cells, run_fields(conn, family))
    return cells


def _raw(cells: dict[str, Cells], where: str) -> Optional[tuple[str, str]]:
    sheet, addr = where.rsplit("!", 1)
    col, row = split_ref(addr)
    return cells.get(sheet, {}).get(row, {}).get(col)


def plan_import(conn, family: RunFamily, path: str, setup: dict) -> tuple[Plan, dict]:
    """The figures to import and what the workbook says of itself. `setup` holds the run's confirmed `unit`
    and `year_end`. Raises `Refused` (one sentence) or `xlsx_cells.WorkbookUnreadable`."""
    cells = read_cells(path)
    said = facts(cells)
    fields = run_fields(conn, family)
    _check_fit(family, setup, said, cells, fields)
    try:
        read = read_filled_workbook(conn, family, path)
    except NothingMatches as exc:
        raise Refused(str(exc)) from exc
    if not any(key[1] == "PY" for key in read.cells):
        raise Refused("The workbook has no last-year column, so it was set up for first financial statements; "
                      "attach one rolled forward from last year's filing.")
    plan = Plan(loose=list(read.loose))
    for key, cell in sorted(read.cells.items()):
        if cell.value is None:   # blank, or a total left to its formula: never imported, never zero
            continue
        info = fields.get(key[0])
        if info is None:
            continue
        raw = _raw(cells, cell.workbook_cell)
        if key[1] == "CY" and not info.is_total and raw is not None and raw[0] == "F":
            plan.formulas_left.append(cell.workbook_cell)
            continue
        plan.figures.append(Planned(key, float(cell.value), "prior_workbook" if key[1] == "PY"
                                    else "typed_in_workbook", info.is_total, cell.workbook_cell))
    for key, unread in sorted(read.unread.items()):
        if unread.holds_value:
            plan.not_imported.append({"cell": unread.workbook_cell, "sentence": unread.sentence,
                                      "period": key[1], "entity_scope": key[2]})
    if not plan.figures:
        raise Refused("The workbook holds no figures for this run's statements, so there is nothing to start "
                      "from.")
    return plan, said


def source_ref(sha256: str, cell: str) -> str:
    """What an imported figure's `source_ref` holds: the workbook's hash and the cell it came from."""
    return json.dumps({"sha256": sha256, "cell": cell}, sort_keys=True)

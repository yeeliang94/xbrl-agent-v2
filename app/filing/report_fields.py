"""The three reports' short fields into an mTool workbook: what to write, and
what not to, with the reason in plain words (step 10g).

Rebuilt from v1 `reports/exporter.py` (`resolve_reports`, `_column_inputs`).
`plan_reports` is pure: it reads nothing and writes nothing.

Where a field goes. The report's sheet is the one sheet that carries the
report's narrative SSM name (mTool names them DirectorsRep, StatOfDirectors,
AuditReport or Auditorsreport; the app's templates name them otherwise). On
that sheet, the row that carries the field's SSM name takes its value in the
one unlocked cell on that row. A field named once at the head of a table
column (the auditor's details) takes its value in the one unlocked typing
cell below it, inside the same table. No cell, or more than one, is listed
and nothing is guessed. A field whose cells are all locked is one mTool sets
with its own picker: it is listed for the person to set in mTool.

How a value goes in (v1's rules, kept):

- a choice only when the cell's own list offers exactly that choice;
- a date only when the cell checks for a date, as the Excel day number;
- the auditor's licence only as four digits, and the audit firm's number only
  as AF and four digits (taken from the printed text, such as "AF 0758",
  when it holds exactly one). mTool's own notes on the sheet ask for these.
  Anything else is listed for a person, never shortened by guesswork;
- every other text exactly as saved, identity numbers included.

A field a person cleared empties its cell. A field the document does not
show, or nobody read, is left as it is and listed.

In a starting workbook a cell the fill does not write may still hold last
year's value. Every candidate cell of every field the fill does not write is
checked, the locked picker cells and the fields of a report nobody read
included: one that holds a value is kept as in the workbook and listed for a
check (`kept_workbook_value`, needs review; `in_mtool_kept` for a value the
run has but mTool's picker must set). The same goes for a report's
text block: when this fill writes no text for it and the workbook's text
block holds text, it is kept and listed (`narrative_kept`). When a person
cleared the report's text, the old text block is listed for the person to
remove in mTool (`narrative_clear_in_mtool`), not removed here: taking a text
block out means deleting its note-store row, its `fn_` name and mTool's
marker in a locked cell, a shape v1 never proved inside mTool, and a half
removal would leave mTool a broken text block.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from app.catalog.reports import REPORTS, narrative_field, report_name
from app.filing.notes import label_column
from app.workbook.mtool_layout import Occurrences
from app.workbook.xlsx_cells import Cells, col_to_idx, sheet_paths, split_ref

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_TABLE_END = {"#LAYOUTSCER#", "#LAYOUTECER#"}
LICENCE, FIRM = "ssmt_LicenseNumberOfAuditor", "ssmt_RegistrationNumberOfAuditFirm"

REPORT_REASONS = {
    "written": "Written and read back.",
    "cleared": "Cleared on purpose, so the cell was emptied.",
    "not_shown": "The document does not show this, so the cell is left empty.",
    "not_assessed": "Nobody has read this field yet, so the cell is left as it is.",
    "no_reports": "Nobody has read this report, so none of its fields was written.",
    "unsure": "The value is not settled, so it was not written. Check it in Reports.",
    "narrative_missing": "The report's text is not filled, so mTool's text block is left as it is.",
    "in_mtool": "mTool sets this field with its own picker, so choose it in mTool.",
    "no_sheet": "The template has no sheet for this report.",
    "no_cell": "The template has no input cell for this field.",
    "ambiguous": "More than one cell could take this field, so none was chosen.",
    "licence_format": "mTool takes the auditor's licence as four digits, so check the licence number in Reports.",
    "firm_format": "mTool takes the audit firm's number as AF and four digits, so check the number in Reports.",
    "choice_not_listed": "The cell's own list does not offer this choice, so it was not written.",
    "not_a_date_cell": "The cell does not take a date, so the date was not written.",
    "formula": "The template works this cell out with a formula, so it was not typed over.",
    "kept_workbook_value": "The run has no value for this, so the workbook's own value was kept as in the "
                           "workbook. Check it.",
    "in_mtool_kept": "mTool sets this field with its own picker, and the workbook still holds its old value, "
                     "so check it in mTool.",
    "narrative_kept": "The run has no text for this report, so the workbook's own text block was kept as in the "
                      "workbook. Check it.",
    "narrative_clear_in_mtool": "The report's text was cleared, but the workbook still holds its old text block, "
                                "so remove it in mTool.",
    "read_back": "The filled file does not hold the value written, so check this field.",
    "not_written": "The field could not be written into the template.",
}


@dataclass
class ReportPlan:
    writes: list[dict] = field(default_factory=list)       # for the patcher's `fill_report_fields`
    skipped: list[dict] = field(default_factory=list)      # left on purpose
    unresolved: list[dict] = field(default_factory=list)   # needs a person


def report_sheets(occurrences: Occurrences, standard: str) -> dict[str, Optional[str]]:
    """{report: the workbook sheet carrying its narrative, or None when not exactly one}."""
    out = {}
    for report in REPORTS:
        sheets = {s for s, _r, _c in occurrences.get(narrative_field(report, standard).element_id, [])}
        out[report] = next(iter(sheets)) if len(sheets) == 1 else None
    return out


def _validations(data: dict, sheet: str) -> list[ET.Element]:
    path = sheet_paths(data).get(sheet)
    if path is None or path not in data:
        return []
    return ET.fromstring(data[path]).findall("m:dataValidations/m:dataValidation", _NS)


def _covers(sqref: str, addr: str) -> bool:
    col, row = split_ref(addr)
    for region in sqref.split():
        ends = region.replace("$", "").split(":")
        (c1, r1), (c2, r2) = split_ref(ends[0]), split_ref(ends[-1])
        if r1 <= row <= r2 and col_to_idx(c1) <= col_to_idx(col) <= col_to_idx(c2):
            return True
    return False


def epoch(data: dict) -> date:
    """Day 0 of the workbook's date numbers (the 1904 system when the workbook says so)."""
    props = ET.fromstring(data["xl/workbook.xml"]).find("m:workbookPr", _NS)
    return date(1904, 1, 1) if props is not None and props.get("date1904") in {"1", "true"} else date(1899, 12, 30)


def _inputs(cells: Cells, row: int, marker_col: str, locked: Callable[[str], bool]) -> tuple[list[str], list[str]]:
    """(unlocked, locked) value cells for the SSM name at (row, marker_col): the row's own cells, or a
    table column's typing cells below its header row."""
    same = [col for col, (kind, _t) in cells.get(row, {}).items() if col != marker_col and kind in "ENS"]
    open_ = [f"{c}{row}" for c in same if not locked(f"{c}{row}")]
    if open_:
        return open_, []
    header = cells.get(row, {})
    if sum("#ssmt_" in str(text) for _k, text in header.values()) >= 2:
        below_open, below_locked = [], []
        for below in sorted(r for r in cells if row < r <= row + 20):
            values = cells[below]
            if any(str(text) in _TABLE_END for _k, text in values.values()):
                break
            if values.get(marker_col, ("X", ""))[0] in "ENS":
                (below_locked if locked(f"{marker_col}{below}") else below_open).append(f"{marker_col}{below}")
        if below_open or below_locked:
            return below_open, below_locked
    right = [c for c in same if col_to_idx(c) > col_to_idx(marker_col) and cells[row][c][0] in "EN"]
    return [], [f"{c}{row}" for c in right]


def _row_values(cells: Cells, row: int, marker_col: str) -> list[str]:
    """Every cell right of the label column on a field's own row: where mTool keeps the field's value, picker
    or typed. None for a table's header row, whose cells are the columns' SSM names."""
    header = cells.get(row, {})
    if sum("#ssmt_" in str(text) for _k, text in header.values()) >= 2:
        return []
    label = label_column(cells, row)
    if label is None:
        return []
    return [f"{c}{row}" for c, (kind, _t) in header.items()
            if c != marker_col and kind != "F" and col_to_idx(c) > col_to_idx(label)]


def _layout_row(cells: Cells, row: int) -> bool:
    """A row of mTool's table furniture (#PRIM#, #TABLE# and the like): its text is the template's own."""
    return any(re.fullmatch(r"#[A-Z]+#", str(text or "").strip()) for _k, text in cells.get(row, {}).values())


def _holds(cells: Cells, addr: str) -> bool:
    col, row = split_ref(addr)
    kind, text = cells.get(row, {}).get(col, ("E", ""))
    return kind in ("N", "S") and bool(str(text or "").strip())


def plan_reports(values: list[dict], standard: str, data: dict, cells: dict[str, Cells], occurrences: Occurrences,
                 *, locked: Callable[[str, str], bool], narratives: frozenset[str] = frozenset(),
                 starting: bool = False, held_narratives: Optional[dict[str, str]] = None,
                 narrative_status: Optional[dict[str, str]] = None) -> ReportPlan:
    """The report writes and the fields left out. `values` is `reports.store.fill_values`; `locked(sheet,
    cell)` says whether the workbook locks a cell; `narratives` names the reports whose narrative is
    filled (the note fill writes it); `starting` says the workbook is a starting workbook;
    `held_narratives` is {report: "Sheet!E15"} for each report whose text block in the starting workbook
    holds text that this fill does not replace; `narrative_status` is {report: the narrative's status}."""
    plan = ReportPlan()
    sheets = report_sheets(occurrences, standard)
    day0 = epoch(data)
    held_narratives = held_narratives or {}
    narrative_status = narrative_status or {}
    read = {r for r in REPORTS if r in narratives
            or any(v["report"] == r and v["status"] != "not_assessed" for v in values)}
    for report in REPORTS:
        f = narrative_field(report, standard)
        narrative = {"report": report, "element_id": f.element_id, "field_id": f.field_id, "label": f.label,
                     "name": f"{f.label.lstrip('*').strip()}, {report_name(report).lower()}", "value": None,
                     "cell": None}
        if report not in read:
            plan.skipped.append({"report": report, "element_id": "", "field_id": report, "label": "",
                                 "name": report_name(report), "value": None, "cell": None, "code": "no_reports",
                                 "reason": REPORT_REASONS["no_reports"]})
        if report in held_narratives:
            code = "narrative_clear_in_mtool" if narrative_status.get(report) == "cleared" else "narrative_kept"
            plan.unresolved.append({**narrative, "cell": held_narratives[report], "code": code,
                                    "reason": REPORT_REASONS[code]})
        elif report in read and report not in narratives:
            plan.skipped.append({**narrative, "code": "narrative_missing",
                                 "reason": REPORT_REASONS["narrative_missing"]})
    for v in values:
        entry = {"report": v["report"], "element_id": v["element_id"], "label": v["label"],
                 "name": f"{v['label'].lstrip('*').strip()}, {report_name(v['report']).lower()}",
                 "value": v["value"], "cell": None}
        sheet = sheets.get(v["report"])

        def out(where: list, code: str, cell: Optional[str] = None) -> None:
            where.append({**entry, "cell": f"{sheet}!{cell}" if cell else None, "code": code,
                          "reason": REPORT_REASONS[code]})

        def kept_value(candidates: list[str], code: str = "kept_workbook_value") -> bool:
            """In a starting workbook, a candidate cell the fill leaves that still holds a value is listed."""
            holding = [c for c in candidates if _holds(cells[sheet], c)] if starting and sheet else []
            if holding:
                out(plan.unresolved, code, holding[0])
            return bool(holding)

        if sheet is None:
            if v["report"] in read:
                out(plan.unresolved, "no_sheet")
            continue
        found = [(r, c) for s, r, c in occurrences.get(v["element_id"], []) if s == sheet]
        open_, shut, values_at = [], [], []
        for row, marker_col in found:
            o, s = _inputs(cells[sheet], row, marker_col, lambda addr: locked(sheet, addr))
            open_ += o
            shut += s
            values_at += _row_values(cells[sheet], row, marker_col)
        open_, shut = sorted(set(open_)), sorted(set(shut))
        candidates = [c for c in dict.fromkeys(open_ + shut + values_at)   # every cell that may hold its value
                      if not _layout_row(cells[sheet], split_ref(c)[1])]
        target = open_[0] if len(open_) == 1 else None
        status = v["status"]
        if v["report"] not in read:
            kept_value(candidates)
            continue
        if status in ("not_shown", "unsure", "not_assessed"):
            if not kept_value(candidates):
                out(plan.unresolved if status == "unsure" else plan.skipped, status, target)
            continue
        if not open_:
            if not kept_value(candidates, "in_mtool_kept" if shut else "kept_workbook_value"):
                out(plan.skipped if shut else plan.unresolved, "in_mtool" if shut else "no_cell")
            continue
        if target is None:
            out(plan.unresolved, "ambiguous")
            continue
        col, row = split_ref(target)
        if cells[sheet].get(row, {}).get(col, ("E", ""))[0] == "F":
            out(plan.skipped, "formula", target)
            continue
        write = {**entry, "cell": f"{sheet}!{target}", "sheet": sheet, "address": target, "kind": "text",
                 "written": v["value"]}
        if status == "cleared":
            plan.writes.append({**write, "kind": "blank", "written": None, "code": "cleared"})
            continue
        value = str(v["value"])
        rules = [x for x in _validations(data, sheet) if _covers(x.get("sqref", ""), target)]
        if v["element_id"] == LICENCE:
            if not re.fullmatch(r"[0-9]{4}", value.strip()):
                out(plan.unresolved, "licence_format", target)
                continue
            write["written"] = value.strip()
        elif v["element_id"] == FIRM:
            numbers = set(re.findall(r"(?<![A-Za-z0-9])AF\s*([0-9]+)(?![A-Za-z0-9])", value, flags=re.I))
            if len(numbers) != 1 or not re.fullmatch(r"[0-9]{4}", next(iter(numbers))):
                out(plan.unresolved, "firm_format", target)
                continue
            write["written"] = "AF" + numbers.pop()
        elif v["kind"] == "choice":
            listed = next((x.findtext("m:formula1", "", _NS) for x in rules if x.get("type") == "list"), "")
            choices = listed[1:-1].split(",") if listed.startswith('"') and listed.endswith('"') else []
            if value not in choices:
                out(plan.unresolved, "choice_not_listed", target)
                continue
        elif v["kind"] == "date":
            if not any(x.get("type") == "date" for x in rules):
                out(plan.unresolved, "not_a_date_cell", target)
                continue
            write.update(kind="date_serial", written=(date.fromisoformat(value) - day0).days)
        plan.writes.append({**write, "code": "written"})
    return plan

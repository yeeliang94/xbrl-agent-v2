"""The fill into a run's starting workbook: keep what came from it, and prove
it is unchanged before any file is released (step 10g).

Rebuilt from v1 `api/mtool.py` (the typed current-year handling) and
`concept_model/prior_year.py` (`validate_export_source`,
`verify_preservation`), with the owner's rule of 18 November 2026: this
year's figures a person typed in the workbook are kept, never overwritten
(v1 overwrote them).

What the fill does with each cell of the starting workbook:

- a figure imported from it (last year's, locked, or this year's typed) is
  not written: "kept as in the workbook". Counted, not listed;
- a typed figure a person then changed in the app is written with the
  person's value and listed as replaced. A person may edit a typed figure in
  the app (the figure store lets a person, never an agent, change one), and
  that edit is the person's own decision about this year's filing, so the
  filed workbook must show it. A person who cleared one leaves the cell as it
  is, listed: blanking a typed figure is left to the person in mTool;
- a cell on a field's row that holds a value the run did not import (a cell
  the import could not read, a formula a person typed in this year's
  column) is kept and listed, and no figure of the run is written over it.
  Numbers on no field's row (the import lists them as loose; the genuine
  templates carry some of their own) are kept by the release check but not
  listed again: no figure can go there;
- every other cell is the template's, and the fill writes as on a template.

The release check (`verify`): every cell the fill did not plan to write
reads the same in the filled file as in the starting workbook, its XML and
its value, and every imported formula works out to the same amount (a
last-year formula that adds up this year's cells would change once this
year is filled). Anything else refuses the file in one sentence.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.catalog.lookup import run_family
from app.filing.plan import FigurePlan
from app.starting import store as starting, workbook
from app.workbook.offline_fill import find_footnote_sheet
from app.workbook.xlsx_cells import Cells, load_entries, read_sheet_cells, shared_strings, sheet_paths, \
    split_ref, taxonomy_ids
from app.workbook.xlsx_formulas import FormulaNotWorkedOut, calculated_value, formula_cells

KEPT_REASONS = {
    "in_workbook": "Kept as in the workbook.",
    "person_edit": "A person changed this figure in the app, so their value replaced the workbook's.",
    "person_cleared": "A person cleared this figure in the app, but the workbook holds it, so it was kept as "
                      "in the workbook. Clear it in mTool if it should go.",
    "workbook_value": "The workbook already holds a value in this cell that was not imported, so it was kept "
                      "as in the workbook and the run's figure was not written. Check it.",
    "not_imported": "The workbook holds a value here that the run has no figure for, so it was kept as in the "
                    "workbook. Check it.",
    "run_differs": "The run holds another amount than the workbook for this figure, so the workbook's was kept "
                   "and the run's was not written. Check which is right and correct it in mTool or in the app.",
    "prior_year_added": "Last year's filing had no figure here, so the run's figure was written into last year's "
                        "column. Check it against last year's filing.",
    "formula_left": "A person put a formula in this year's cell in the workbook, so it was kept as in the "
                    "workbook. Check it.",
}


class ReleaseRefused(ValueError):
    """The filled file is not released; `str()` is one plain sentence."""


@dataclass
class Starting:
    path: Path
    filename: str
    sha256: str
    imported: list[dict]          # `starting.store.imported_cells`
    summary: dict                 # the import's summary (`starting_workbooks.import_json`)


def load(conn: sqlite3.Connection, run_id: int) -> Optional[Starting]:
    """The run's starting workbook, checked against its hash and against the run's setup as it is now (a
    scope answer may not change the setup under it, but the fill does not rely on that), or None. Raises
    `starting.workbook.Refused`."""
    path = starting.path_of(conn, run_id)
    if path is None:
        return None
    setup = conn.execute("SELECT unit, year_end FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
    try:
        workbook.check_fit(conn, run_family(conn, run_id), str(path), dict(setup) if setup else {})
    except workbook.Refused as exc:
        why = str(exc).split(", so ")[0].rstrip(".;")
        raise workbook.Refused(f"{why}, so this run's setup no longer fits the starting workbook and no file was "
                               "made; start a new run with it.") from exc
    row = conn.execute("SELECT filename, sha256, import_json FROM starting_workbooks WHERE run_id = ?",
                       (run_id,)).fetchone()
    return Starting(path, row["filename"], row["sha256"], starting.imported_cells(conn, run_id),
                    json.loads(row["import_json"]) if row["import_json"] else {})


def _value(cells: dict[str, Cells], ref: str) -> tuple[str, str]:
    sheet, addr = ref.rsplit("!", 1)
    col, row = split_ref(addr)
    return cells.get(sheet, {}).get(row, {}).get(col, ("E", ""))


def _holds(cells: dict[str, Cells], ref: str) -> bool:
    kind, text = _value(cells, ref)
    return kind == "F" or (kind in ("N", "S") and bool(str(text or "").strip()))


def _cell_name(cells: dict[str, Cells], ref: str) -> str:
    """A workbook cell in words: its row's label and its sheet, never its address."""
    sheet, addr = ref.rsplit("!", 1)
    row = split_ref(addr)[1]
    label = next((str(t).lstrip("*").strip() for _c, (k, t) in sorted(cells.get(sheet, {}).get(row, {}).items())
                  if k == "S" and str(t).strip() and not taxonomy_ids(t) and not str(t).startswith("#")), "")
    return f"{label}, {sheet} sheet" if label else f"A value on the {sheet} sheet"


def _line(code: str, name: str, cell: Optional[str], **extra) -> dict:
    return {"name": name, "workbook_cell": cell, "cell": cell, "code": code, "reason": KEPT_REASONS[code], **extra}


def _same(cells: dict[str, Cells], ref: str, value) -> bool:
    """Whether the workbook's cell holds this amount as a typed number. Only this year's typed figures are
    compared; they are numbers (a formula in this year's cell is never imported)."""
    kind, text = _value(cells, ref)
    try:
        return kind == "N" and abs(float(text) - float(value)) < 1e-9
    except (TypeError, ValueError):
        return False


def keep(plan: FigurePlan, start: Starting, cells: dict[str, Cells]) -> dict:
    """Take out of `plan.writes` every write the starting workbook keeps. Returns {"kept_in_workbook",
    "replaced", "workbook_kept", "prior_year_added"}: imported figures kept (counted), person edits written
    (listed), the workbook's own values kept (listed), and last-year figures written where the workbook had
    none (written and listed). An imported figure whose run value differs from its cell for any other reason
    is not written and goes to `plan.unresolved`."""
    by_cell = {entry["cell"]: entry for entry in start.imported}
    by_key = {tuple(entry["key"]): entry for entry in start.imported}
    kept, replaced, listed, writes, added = [], [], [], [], []
    for w in plan.writes:
        key = (w["concept_uuid"], w["period"], w["entity_scope"], w["dimension_key"])
        entry = by_cell.get(w["cell"]) or by_key.get(key)
        if entry is not None:
            if entry["locked"] or _same(cells, entry["cell"], w["value"]):
                # Last year's figures are locked for everyone, so they are as imported.
                kept.append({**w, "code": "in_workbook", "reason": KEPT_REASONS["in_workbook"]})
            elif entry["origin"] == "person" and entry["cell"] == w["cell"]:
                writes.append(w)
                replaced.append({**w, "code": "person_edit", "reason": KEPT_REASONS["person_edit"]})
            else:   # never kept silently: the app shows another amount than the file would
                plan.unresolved.append({**{k: v for k, v in w.items() if k not in ("sheet", "address")},
                                        "code": "run_differs", "reason": KEPT_REASONS["run_differs"]})
        elif _holds(cells, w["cell"]):
            listed.append({**w, "workbook_cell": w["cell"], "code": "workbook_value",
                           "reason": KEPT_REASONS["workbook_value"]})
        else:
            writes.append(w)
            if w["period"] == "PY":
                added.append({**w, "code": "prior_year_added", "reason": KEPT_REASONS["prior_year_added"]})
    plan.writes = writes
    names = {(x["concept_uuid"], x["period"], x["entity_scope"], x["dimension_key"]): x["name"]
             for x in plan.skipped + plan.unresolved}
    for entry in start.imported:
        if entry["value"] is None and entry["person_edited"]:
            listed.append(_line("person_cleared", names.get(tuple(entry["key"])) or _cell_name(cells, entry["cell"]),
                                entry["cell"], concept_uuid=entry["key"][0], period=entry["key"][1],
                                entity_scope=entry["key"][2], dimension_key=entry["key"][3]))
    for item in start.summary.get("not_imported", []):
        if item.get("cell"):
            listed.append(_line("not_imported", _cell_name(cells, item["cell"]), item["cell"],
                                detail=item.get("sentence", "")))
    for ref in start.summary.get("formulas_left", []):
        listed.append(_line("formula_left", _cell_name(cells, ref), ref))
    return {"kept_in_workbook": kept, "replaced": replaced, "workbook_kept": listed, "prior_year_added": added}


# The release check ------------------------------------------------------------

def _cell_xml(sheet_xml: bytes) -> dict[str, str]:
    return {c.get("r"): ET.tostring(c, encoding="unicode") for c in ET.fromstring(sheet_xml).iter()
            if c.tag.rsplit("}", 1)[-1] == "c" and c.get("r")}


def _flat(cells: Cells) -> dict[str, tuple[str, str]]:
    return {f"{col}{row}": cell for row, row_cells in cells.items() for col, cell in row_cells.items()}


def _worked_out(cells: dict[str, Cells], ref: str):
    sheet, addr = ref.rsplit("!", 1)
    try:
        return calculated_value(cells, sheet, addr)
    except FormulaNotWorkedOut:
        return None


def verify(before: Path, after: Path, planned: set[str], start: Starting) -> dict:
    """Refuse (`ReleaseRefused`) a filled file in which anything of the starting workbook changed that the fill
    did not plan to write. `planned` holds every cell the fill planned to write ("Sheet!E25"); the hidden
    note store is the fill's own. Returns the check's counts."""
    old, new = load_entries(str(before)), load_entries(str(after))
    paths = sheet_paths(old)
    if sheet_paths(new) != paths:
        raise ReleaseRefused("The fill changed the starting workbook's sheets, so no file was released.")
    old_sst, new_sst = shared_strings(old), shared_strings(new)
    strings_kept = new_sst[:len(old_sst)] == old_sst
    imported = {entry["cell"]: entry for entry in start.imported}
    note_store = find_footnote_sheet(paths)
    changed: list[str] = []
    checked = 0
    for sheet, path in paths.items():
        if sheet == note_store or path not in old:
            continue
        if old[path] == new.get(path) and strings_kept:
            continue
        xml_a, xml_b = _cell_xml(old[path]), _cell_xml(new[path])
        val_a, val_b = _flat(read_sheet_cells(old[path], old_sst)), _flat(read_sheet_cells(new[path], new_sst))
        for addr in set(xml_a) | set(xml_b):
            ref = f"{sheet}!{addr}"
            if ref in planned:
                continue
            checked += 1
            if xml_a.get(addr) != xml_b.get(addr) or val_a.get(addr) != val_b.get(addr):
                changed.append(ref)
    if changed:
        hit = sorted(changed, key=lambda r: (r not in imported, r))[0]
        what = "A figure imported from" if hit in imported else "A cell of"
        raise ReleaseRefused(f"{what} the starting workbook changed during the fill ({hit}), so no file was "
                             "released.")
    kept = [ref for ref, entry in imported.items() if ref not in planned]
    formulas_a, formulas_b = formula_cells(old), formula_cells(new)
    for ref in kept:
        if _value(formulas_a, ref)[0] != "F":
            continue
        before_value = _worked_out(formulas_a, ref)
        if before_value is not None and _worked_out(formulas_b, ref) != before_value:
            raise ReleaseRefused(f"Last year's figure in {ref} is a formula that uses this year's cells, so filling "
                                 "this year would change it and no file was released. Type its value over the "
                                 "formula in the workbook and start a new run with it.")
    return {"imported_kept": len(kept), "cells_checked": checked}

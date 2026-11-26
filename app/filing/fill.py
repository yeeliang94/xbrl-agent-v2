"""Fill an mTool template from a run: the one plain entry point.

Rebuilt from the joining code in v1's route (`api/mtool.py` 523-1056), less
the route, the job, the receipt table and the readiness check (step 8e
builds those around this function).

    report = fill_workbook(run_id, template_path, output_path)

In order: read the template, identify it, place the run's fields on it
(`app/workbook/mtool_map.py`, as scoring does), plan the figures
(`plan.plan_figures`), the notes and the reports' narratives
(`notes.plan_notes`) and the reports' short fields
(`report_fields.plan_reports`), write them with the one patcher
(`app/workbook/offline_fill.py`, and `report_cells.py` beside it for the
report fields), then read the filled file back by meaning
and check every figure written is where scoring will read it, with the value
written. The template is never changed; the output is a new file, written
atomically.

A run with a starting workbook (step 10g) is filled into a copy of that
workbook instead (`template_path` None, or that same file): what came from it
is kept (`starting_fill.keep`), and the file is released only when every cell
the fill did not plan to write is unchanged (`starting_fill.verify`).

The report (a plain dict, JSON-ready):

    {
      "run_id": int,
      "status": "ok" | "needs review",   # needs review: anything unresolved, mismatched,
                                         # a note left out, or a template that is not known
      "template": {"sha256", "fingerprint", "compatibility" ("known" | "probably_compatible" |
                   "unknown"), "name", "reasons": [sentence]},   # also: its unit differs from the run's
      "output": {"path", "sha256"},
      "figures_digest": str, "notes_digest": str,   # which revision of the figures and notes
      "written" | "kept" | "skipped" | "unresolved" | "mismatched": [FigureLine],
      "notes": {"written" | "skipped" | "unresolved" | "mismatched": [NoteLine]},
      "reports": {"written" | "skipped" | "unresolved" | "mismatched": [ReportLine]},
      "starting": None | {"filename", "sha256", "imported_kept", "cells_checked",
                          "kept_in_workbook" | "replaced" | "workbook_kept": [line]},
      "counts": {"written", "kept", "skipped", "unresolved", "mismatched", "notes_written",
                 "notes_not_written", "reports_written", "reports_not_written",
                 "kept_in_workbook", "replaced", "workbook_kept"},
    }

    FigureLine: {"concept_uuid", "period", "entity_scope", "dimension_key", "field", "statement",
                 "name" (the figure in words, e.g. "Trade receivables, Group, 2025"), "value",
                 "cell" ("Sheet!E25" or None; for debugging, never shown as the line's name),
                 "code", "reason" (one plain sentence)}
    NoteLine:   {"field_id", "field", "name", "template", "revision", "chars", "tier", "cell", "code",
                 "reason"}
    ReportLine: {"report", "element_id", "label", "name", "value" (as saved), "written" (as written,
                 such as "AF0758" or a date's day number), "cell", "code", "reason"}

Raises `app.workbook.xlsx_cells.WorkbookUnreadable` for a file that is not a
workbook, and `FillError` (one plain sentence for a person) for a run that
does not exist, an output that is the template itself, a starting workbook
that changed, or a filled file the release check refuses (no file is left). Anything else is a
fault, not a sentence for a person.

A line the patcher refused with an error keeps that error as `detail`
(logged, kept in the report, never shown on the receipt).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Optional

from app import db
from app.catalog.fields import run_fields
from app.catalog.lookup import concept as catalog_concept, row_totals, run_family
from app.catalog.note_fields import run_note_fields
from app.catalog.reports import report_note_fields
from app.figures.store import run_figures
from app.filing import mappings, starting_fill
from app.workbook.toolkit.book import row_label
from app.filing.identify import KNOWN, fingerprint, identify
from app.filing.notes import NOTE_REASONS, plan_notes, text_block_cell
from app.filing.plan import REASONS, plan_figures
from app.filing.report_fields import REPORT_REASONS, plan_reports, report_sheets
from app.reports import store as report_store
from app.runs import units
from app.starting.workbook import Refused as StartingRefused, facts as workbook_facts
from app.utils.paths import PathLike, safe_entry_path, safe_path
from app.workbook import mtool_layout, mtool_map, offline_fill, report_cells
from app.workbook.mtool_map import CellRef, Key
from app.workbook.xlsx_cells import read_workbook, sheet_paths, split_ref

logger = logging.getLogger(__name__)


class FillError(ValueError):
    """The fill cannot go ahead; `str()` is one plain sentence for a person."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(rows) -> str:
    return hashlib.sha256(json.dumps(sorted(rows), default=str).encode("utf-8")).hexdigest()


def _note_texts(conn, run_id: int, note_fields) -> dict:
    from app.notes import field_text

    house = field_text.house(conn)
    texts = {}
    for note_field in note_fields:
        if not note_field.heading:
            text = field_text.prepared(conn, run_id, note_field.field_id, house)
            if text is not None:
                texts[note_field.field_id] = text
    return texts


def _number(cell) -> Optional[float]:
    if not cell or cell[0] != "N":
        return None
    try:
        return float(cell[1])
    except (TypeError, ValueError):
        return None


def _read_back(output: Path, written: list[dict], fields, family,
               confirmed: Optional[dict[Key, CellRef]] = None) -> tuple[list[dict], list[dict]]:
    """Every written figure read back by meaning: the same cell, the same value. A figure placed by a
    person's confirmed mapping is read back from its confirmed cell."""
    _, cells = read_workbook(str(output))
    placed = mtool_map.map_fields(cells, fields, family)
    cell_of: dict[Key, CellRef] = {**{key: cell for cell, claims in placed.claims.items() if len(claims) == 1
                                      for key, _ in claims}, **(confirmed or {})}
    ok, wrong = [], []
    for line in written:
        key = (line["concept_uuid"], line["period"], line["entity_scope"], line["dimension_key"])
        sheet, addr = line["cell"].rsplit("!", 1)
        col, row = split_ref(addr)
        found = _number(cells.get(sheet, {}).get(row, {}).get(col))
        if cell_of.get(key) != (sheet, row, col) or found is None or abs(found - line["value"]) > 1e-9:
            wrong.append({**line, "code": "read_back", "reason": REASONS["read_back"]})
        else:
            ok.append({**line, "code": "written", "reason": REASONS["written"]})
    return ok, wrong


def _errors_by_line(errors: list[dict], run_id: int, what: str) -> dict[int, str]:
    """{line: the patcher's error}, each logged."""
    out = {}
    for error in errors:
        logger.warning("mTool fill: run %s %s line %s not written: %s", run_id, what, error.get("line"),
                       error.get("error"))
        if "line" in error:
            out[error["line"]] = str(error.get("error", ""))
    return out


def _strip(line: dict) -> dict:
    return {k: v for k, v in line.items() if k not in ("sheet", "address", "html", "index", "action",
                                                       "key", "hidden_sheet", "hidden_cell", "slot_source")}


def _report_lines(plan, result: dict, run_id: int) -> dict:
    """The report fields' outcome after the patcher: written, skipped, unresolved, mismatched."""
    done = {w["line"] for w in result["written"]}
    wrong = {w["line"] for w in result["mismatches"]}
    refused = {**{w["line"]: "formula" for w in result["skipped_formula"]},
               **{w["line"]: "in_mtool" for w in result["locked"]}}
    errors = _errors_by_line(result["errors"], run_id, "report field")

    def line(i: int, code: str) -> dict:
        item = {k: v for k, v in plan.writes[i].items() if k not in ("sheet", "address", "kind")}
        out = {**item, "code": code, "reason": REPORT_REASONS[code]}
        return {**out, "detail": errors[i]} if i in errors else out

    count = range(len(plan.writes))
    return {"written": [line(i, plan.writes[i]["code"]) for i in count if i in done and i not in wrong],
            "skipped": list(plan.skipped) + [line(i, refused[i]) for i in count if i in refused],
            "unresolved": list(plan.unresolved) + [line(i, "not_written") for i in count
                                                   if i not in done and i not in refused],
            "mismatched": [line(i, "read_back") for i in sorted(wrong)]}


def _held_narratives(path: Path, narratives, note_plan, cells, occurrences) -> dict[str, str]:
    """{report: "Sheet!E15"} for each report whose text block in the starting workbook holds text (a stored
    payload, or anything in the visible cell) that this fill does not replace."""
    writing = {(n["sheet"], n["cell"]) for n in note_plan.items}
    payloads = offline_fill.read_note_payloads(str(path))
    out = {}
    for narrative in narratives:
        sheet, cell, _problem = text_block_cell(narrative, cells, occurrences)
        if cell is None or (sheet, cell) in writing:
            continue
        col, row = split_ref(cell)
        kind, shown = cells[sheet].get(row, {}).get(col, ("E", ""))
        if (payloads.get((sheet, cell)) or "").strip() or (kind in ("S", "N") and str(shown or "").strip()):
            out[narrative.template] = f"{sheet}!{cell}"
    return out


def _source(conn, run_id: int, template_path: Optional[PathLike]):
    """The workbook to fill: the run's starting workbook when it has one, else the template given."""
    try:
        start = starting_fill.load(conn, run_id)
    except StartingRefused as exc:
        raise FillError(str(exc)) from exc
    if start is None:
        if template_path is None:
            raise FillError("Choose an .xlsx or .xlsm mTool template.")
        return safe_path(template_path), None
    if template_path is not None and not os.path.samefile(safe_path(template_path), start.path):
        raise FillError("This run fills the workbook attached at setup, so it cannot fill another template.")
    return start.path, start


def _unit_differs(unit: Optional[str], cells) -> list[str]:
    """One sentence when the template's own level of rounding is not the unit confirmed at setup, else
    nothing. Figures go in as printed, never rescaled, so mTool would read every amount in the wrong unit.
    A template that does not say its rounding cannot be checked and is left alone."""
    said = workbook_facts(cells)["unit"]
    unit = unit or units.RM
    if said is None or said == unit:
        return []
    return [f"The template is in {units.unit_words(said)} but the report is in {units.unit_words(unit)}, so mTool "
            "would read every amount in the wrong unit; make the template in mTool with the same level of "
            "rounding and fill it again."]


def fill_workbook(run_id: int, template_path: Optional[PathLike], output_path: PathLike, *,
                  confirmed_mapping: Optional[dict] = None) -> dict:
    """Fill a copy of the template (or the run's starting workbook) from the run's current figures, notes and
    reports. See the module docstring.

    `confirmed_mapping` is {"name": ..., "cells": {Key: (sheet, row, column)}} for this template, confirmed
    by a person; without it, the mapping saved for the template's fingerprint is used (app/filing/mappings.py,
    step 12)."""
    output = safe_entry_path(output_path)
    logger.info("mTool fill start: run %s", run_id)
    with db.connect() as conn:
        family = run_family(conn, run_id)
        if family is None or not family.standard:
            raise FillError("There is no such run, or its setup is not confirmed.")
        template, start = _source(conn, run_id, template_path)
        year = int(conn.execute("SELECT year FROM runs WHERE id = ?", (run_id,)).fetchone()[0] or 0)
        setup = conn.execute("SELECT unit FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
        fields = run_fields(conn, family)
        figures = run_figures(conn, run_id)
        totals = frozenset(row_totals(conn, set(family.template_ids.values())))
        labels = {uuid: (found.label if (found := catalog_concept(conn, uuid)) else "")
                  for uuid in {f["concept_uuid"] for f in figures} - set(fields)}
        note_fields = run_note_fields(conn, run_id)
        texts = _note_texts(conn, run_id, note_fields)
        report_values = report_store.fill_values(conn, run_id)
        narrative_status = report_store.narrative_statuses(conn, run_id)
        narratives = report_note_fields(conn, family.level, family.standard)
        for narrative in narratives:
            if (text := report_store.narrative_text(conn, run_id, narrative.template)) is not None:
                texts[narrative.field_id] = text
    if output.exists() and os.path.samefile(template, output):
        raise FillError("The filled file must be a new file, so the template is never changed.")

    data, cells = read_workbook(str(template))
    if confirmed_mapping is None:   # placements a person confirmed for this template (step 12)
        with db.connect() as conn:
            confirmed_mapping = mappings.confirmed_for(conn, fingerprint(cells))
        if confirmed_mapping is not None:
            kept_cells = mappings.still_fits(confirmed_mapping,
                                             lambda sheet, row: row_label(cells.get(sheet, {}), row))
            if len(kept_cells["cells"]) < len(confirmed_mapping["cells"]):
                logger.warning("mTool fill: run %s: %d saved place(s) no longer match their row and were not used",
                               run_id, len(confirmed_mapping["cells"]) - len(kept_cells["cells"]))
            confirmed_mapping = kept_cells
    identity = identify(cells, confirmed_mapping=confirmed_mapping)
    logger.info("mTool fill: run %s %s is %s", run_id, "starting workbook" if start else "template",
                identity.compatibility)
    unit_differs = [] if start else _unit_differs(setup["unit"] if setup else None, cells)   # a starting workbook is checked when it is loaded
    if unit_differs:
        logger.warning("mTool fill: run %s: the template's level of rounding differs from the run's unit", run_id)
    placed = mtool_map.map_fields(cells, fields, family)
    protection = offline_fill.protected_input_cells(data, sheet_paths(data))
    locked = lambda sheet, addr: offline_fill.is_locked_input(protection, sheet, addr)  # noqa: E731
    confirmed = {tuple(k): tuple(v) for k, v in (confirmed_mapping or {}).get("cells", {}).items()} or None
    figure_plan = plan_figures(figures, fields, placed, cells, family, year=year, locked=locked,
                               row_totals=totals, labels=labels, confirmed=confirmed)
    kept = starting_fill.keep(figure_plan, start, cells) if start else {"kept_in_workbook": [], "replaced": [],
                                                                        "workbook_kept": [], "prior_year_added": []}
    occurrences = mtool_layout.index_taxonomy(cells)
    native = report_sheets(occurrences, family.standard)
    narratives = [replace(n, sheet=native.get(n.template) or n.sheet) for n in narratives]
    note_plan = plan_notes(note_fields + narratives, texts, cells, occurrences)
    report_plan = plan_reports(report_values, family.standard, data, cells, occurrences, locked=locked,
                               narratives=frozenset(n.template for n in narratives if n.field_id in texts),
                               starting=start is not None,
                               held_narratives=_held_narratives(template, narratives, note_plan, cells, occurrences)
                               if start else None, narrative_status=narrative_status)
    logger.info("mTool fill: run %s plans %d figures, %d notes and %d report fields", run_id,
                len(figure_plan.writes), len(note_plan.items), len(report_plan.writes))

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = []
    for stage in ("numbers", "notes"):
        fd, path = tempfile.mkstemp(prefix=f".fill-{stage}-", suffix=".xlsx", dir=output.parent)
        os.close(fd)
        temporary.append(path)
    numbers_path, notes_path = temporary
    try:
        numbers = offline_fill.fill_workbook(
            str(template), {"writes": [{"sheet": w["sheet"], "cell": w["address"], "value": w["value"],
                                        "line": i} for i, w in enumerate(figure_plan.writes)]},
            numbers_path, force_recalc=True)
        if note_plan.items:
            notes = offline_fill.fill_footnotes(
                numbers_path, {"footnotes": [{"sheet": n["sheet"], "cell": n["cell"], "html": n["html"],
                                              "line": i} for i, n in enumerate(note_plan.items)]}, notes_path)
        else:
            notes_path = numbers_path
            notes = {"footnotes_written": [], "unresolved": [], "errors": [], "footnote_mismatches": []}
        scalars = report_cells.fill_report_fields(
            notes_path, {"writes": [{"sheet": w["sheet"], "cell": w["address"], "kind": w["kind"],
                                     "value": w["written"], "line": i}
                                    for i, w in enumerate(report_plan.writes)]}, str(output))
        if start is not None:
            planned = ({w["cell"] for w in figure_plan.writes} | {w["cell"] for w in report_plan.writes}
                       | {f"{n['sheet']}!{n['cell']}" for n in note_plan.items})
            checked = starting_fill.verify(start.path, output, planned, start)
    except starting_fill.ReleaseRefused as exc:
        logger.error("mTool fill: run %s file not released: %s", run_id, exc)
        output.unlink(missing_ok=True)
        raise FillError(str(exc)) from exc
    except Exception:
        logger.exception("mTool fill failed: run %s", run_id)
        output.unlink(missing_ok=True)
        raise
    finally:
        for path in temporary:
            safe_entry_path(path).unlink(missing_ok=True)

    # The patcher refuses again what the plan already left out; anything it refused is listed.
    done = {w["line"] for w in numbers["written"]}
    refused = {**{w["line"]: "formula" for w in numbers["skipped_formula"]},
               **{w["line"]: "locked" for w in numbers["locked"]}}
    number_errors = _errors_by_line(numbers["errors"], run_id, "figure")
    written = [{**_strip(w), "cell": w["cell"]} for i, w in enumerate(figure_plan.writes) if i in done]
    skipped = list(figure_plan.skipped) + [
        {**_strip(w), "code": refused[i], "reason": REASONS[refused[i]]}
        for i, w in enumerate(figure_plan.writes) if i in refused]
    unresolved = list(figure_plan.unresolved) + [
        {**_strip(w), "code": "not_written", "reason": "The cell could not be written, so check the template.",
         **({"detail": number_errors[i]} if i in number_errors else {})}
        for i, w in enumerate(figure_plan.writes) if i not in done and i not in refused]
    written, mismatched = _read_back(output, written, fields, family, confirmed)

    # A note-store error with no line of its own (a key held twice, no note store) is put on the notes it touches.
    note_errors = _errors_by_line([e for e in notes["errors"] if "line" in e], run_id, "note")
    general = [e for e in notes["errors"] if "line" not in e]
    for error in general:
        logger.warning("mTool fill: run %s note store error: %s", run_id, error.get("error"))
    duplicate_keys = {e["key"]: e["error"] for e in general if e.get("key")}
    others = "; ".join(e.get("error", "") for e in general if not e.get("key"))
    notes_dup = {n["line"]: duplicate_keys[n["key"]] for n in notes["footnotes_written"]
                 if n.get("key") in duplicate_keys}
    notes_wrong = {n["line"] for n in notes["footnote_mismatches"]}
    notes_done = {n["line"] for n in notes["footnotes_written"]} - notes_wrong - set(notes_dup)

    def note_line(i: int, code: str, detail: str = "") -> dict:
        item = note_plan.items[i]
        line = {**_strip(item), "cell": f"{item['sheet']}!{item['cell']}", "code": code, "reason": NOTE_REASONS[code]}
        return {**line, "detail": detail} if detail else line

    note_report = {
        "written": [note_line(i, "written") for i in range(len(note_plan.items)) if i in notes_done],
        "skipped": list(note_plan.skipped),
        "unresolved": list(note_plan.unresolved)
        + [note_line(i, "duplicate_key", notes_dup[i]) for i in sorted(notes_dup) if i not in notes_wrong]
        + [note_line(i, "not_written", note_errors.get(i) or others) for i in range(len(note_plan.items))
           if i not in notes_done and i not in notes_wrong and i not in notes_dup],
        "mismatched": [note_line(i, "read_back") for i in sorted(notes_wrong)],
    }
    reports = _report_lines(report_plan, scalars, run_id)
    report = {
        "run_id": run_id,
        "template": {"sha256": _sha256(template), "fingerprint": identity.fingerprint,
                     "compatibility": identity.compatibility, "name": identity.name,
                     "reasons": identity.reasons + unit_differs},
        "output": {"path": str(output), "sha256": _sha256(output)},
        "figures_digest": _digest((f["concept_uuid"], f["period"], f["entity_scope"], f["dimension_key"],
                                   f["value"], f["origin"]) for f in figures),
        "notes_digest": _digest((uuid, text.revision) for uuid, text in texts.items()),
        "written": written, "kept": figure_plan.kept, "skipped": skipped, "unresolved": unresolved,
        "mismatched": mismatched, "notes": note_report, "reports": reports,
        "starting": None if start is None else {"filename": start.filename, "sha256": start.sha256, **checked,
                                                **{k: [_strip(x) for x in v] for k, v in kept.items()}},
    }
    report["counts"] = {name: len(report[name]) for name in ("written", "kept", "skipped", "unresolved",
                                                              "mismatched")}
    report["counts"].update(notes_written=len(note_report["written"]),
                            notes_not_written=sum(len(note_report[k]) for k in ("skipped", "unresolved",
                                                                                 "mismatched")),
                            reports_written=len(reports["written"]),
                            reports_not_written=sum(len(reports[k]) for k in ("skipped", "unresolved",
                                                                              "mismatched")),
                            **{name: len(lines) for name, lines in kept.items()})
    needs_review = (identity.compatibility != KNOWN or unit_differs or unresolved or mismatched
                    or any(note_report[k] for k in ("skipped", "unresolved", "mismatched"))
                    or reports["unresolved"] or reports["mismatched"]
                    or kept["workbook_kept"] or kept["prior_year_added"])
    report["status"] = "needs review" if needs_review else "ok"
    logger.info("mTool fill end: run %s, %d written, %d unresolved, %d mismatched, %d notes, %d report fields, "
                "%d kept from the starting workbook", run_id, len(written), len(unresolved), len(mismatched),
                len(note_report["written"]), len(reports["written"]), len(kept["kept_in_workbook"]))
    return report

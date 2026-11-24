"""The starting workbook a run keeps, and the import of its figures.

Rebuilt from v1 `concept_model/prior_year.py` (`workbook_path`,
`import_workbook`, `_check_imported_subtotals`) and modelled on the scoring
attachment (`app/scoring/attached.py`): the file is kept in the run's folder
through the safe-path and atomic-write helpers, with its sha256.

When things happen:

- **Attach** (setup only, before extraction): the file is kept and read for
  what it says of itself. Nothing is imported yet, because the standard,
  level, unit, year end and layouts are not settled until a person confirms
  the setup. Attaching again replaces the file and the record; nothing had
  been imported from the earlier one.
- **Import** (`import_at_confirm`, inside the setup confirm's transaction):
  the workbook is checked against the confirmed setup and its figures are
  imported. A workbook that does not fit refuses the confirm in one sentence,
  and nothing of the confirm is kept.
- **Remove** (setup only): the record and the file go. Once the setup is
  confirmed the workbook stays: its figures are in the run, locked or kept
  fixed, and the fill writes into this file (step 10g). So a removal never
  has imported figures to undo.

A typed total and the lines under it are never forced to agree: the total is
imported with no breakdown, and the printed-totals check shows a difference
(v1 opened a conflict row; v2's check does the same job).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from app import db
from app.catalog.lookup import run_family
from app.figures import store as figures
from app.runs import events
from app.starting import workbook
from app.utils.atomic_io import write_bytes_atomic
from app.utils.paths import output_dir, safe_entry_path, safe_path

logger = logging.getLogger(__name__)

SOURCE = "setup"
IMPORTED = ("prior_workbook", "typed_in_workbook")


class NoWorkbook(LookupError):
    """The run has no starting workbook."""


class TooLate(ValueError):
    """The run's setup is confirmed. `str()` is one plain sentence."""


def _row(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM starting_workbooks WHERE run_id = ?", (run_id,)).fetchone()


def _at_setup(conn: sqlite3.Connection, run_id: int, sentence: str) -> None:
    run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None or run["status"] != "setup":
        raise TooLate(sentence)


def _discard(relative: str) -> None:
    try:
        safe_entry_path(output_dir() / relative).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete the unused starting workbook file %s.", relative, exc_info=True)


def _in_use(run_id: int, relative: str) -> bool:
    """True when the run's record keeps this file: another upload of the same workbook saved it meanwhile."""
    with db.connect() as conn:
        row = _row(conn, run_id)
    return row is not None and row["stored_path"] == relative


def path_of(conn: sqlite3.Connection, run_id: int) -> Optional[Path]:
    """The kept file, checked against its hash. None when the run has none.
    Raises `workbook.Refused` when the file changed or is missing."""
    row = _row(conn, run_id)
    if row is None:
        return None
    path = safe_path(output_dir() / row["stored_path"])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
        raise workbook.Refused("The starting workbook changed or is missing since it was attached, so attach "
                               "it again.")
    return path


def attach(run_id: int, data: bytes, *, filename: str, uploaded_by: str) -> dict:
    """Keep the file and read what it says of itself. A refused file leaves any earlier one as it was.
    Raises `TooLate`, `workbook.Refused` or `xlsx_cells.WorkbookUnreadable`."""
    late = "A starting workbook is attached at setup, and this run's setup is already confirmed."
    with db.connect() as conn:
        _at_setup(conn, run_id, late)
    sha = hashlib.sha256(data).hexdigest()
    suffix = ".xlsm" if filename.lower().endswith(".xlsm") else ".xlsx"
    relative = f"runs/run-{int(run_id)}/starting-workbook-{sha[:16]}{suffix}"
    # The name comes from the file's hash, so the same workbook sent again lands on the file already kept.
    # Only a file this call created may be deleted if the attach is refused.
    created = not safe_entry_path(output_dir() / relative).is_file()
    path = write_bytes_atomic(output_dir() / relative, data)
    old = None
    try:
        said = workbook.facts(workbook.read_cells(str(path)))
        with db.connect(immediate=True) as conn:
            _at_setup(conn, run_id, late)
            previous = _row(conn, run_id)
            old = previous["stored_path"] if previous else None
            conn.execute(
                "INSERT INTO starting_workbooks(run_id, filename, sha256, stored_path, facts_json, uploaded_by, "
                "uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                "filename = excluded.filename, sha256 = excluded.sha256, stored_path = excluded.stored_path, "
                "facts_json = excluded.facts_json, uploaded_by = excluded.uploaded_by, "
                "uploaded_at = excluded.uploaded_at, imported_at = NULL, import_json = NULL",
                (run_id, Path(filename).name[:255] or "workbook.xlsx", sha, relative, json.dumps(said),
                 uploaded_by, db.now()))
            events.insert(conn, SOURCE, "starting_workbook",
                          "A starting workbook was attached; its figures are imported when the setup is "
                          "confirmed." if old is None else "The starting workbook was replaced; its figures are "
                          "imported when the setup is confirmed.",
                          run_id=run_id, data={"by": uploaded_by, "sha256": sha, "replaced": old is not None,
                                               **said})
            result = record(conn, run_id)
    except BaseException:
        if created and not _in_use(run_id, relative):
            _discard(relative)
        raise
    if old is not None and old != relative:
        _discard(old)
    logger.info("Run %s: starting workbook attached (%s, sha256 %s).", run_id,
                "replaced" if old else "new", sha[:16])
    return result


def remove(run_id: int, by: str) -> None:
    """Forget the run's starting workbook, at setup only. Raises `NoWorkbook` or `TooLate`."""
    with db.connect(immediate=True) as conn:
        row = _row(conn, run_id)
        if row is None:
            raise NoWorkbook("This run has no starting workbook.")
        _at_setup(conn, run_id, "The starting workbook's figures are already in this run, so it stays attached.")
        conn.execute("DELETE FROM starting_workbooks WHERE run_id = ?", (run_id,))
        events.insert(conn, SOURCE, "starting_workbook", "The starting workbook was removed.", run_id=run_id,
                      data={"by": by, "sha256": row["sha256"]})
    _discard(row["stored_path"])
    logger.info("Run %s: starting workbook removed.", run_id)


def record(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    row = _row(conn, run_id)
    if row is None:
        return None
    return {"filename": row["filename"], "sha256": row["sha256"], "uploaded_by": row["uploaded_by"],
            "uploaded_at": row["uploaded_at"], "workbook": json.loads(row["facts_json"]),
            "imported_at": row["imported_at"],
            "imported": json.loads(row["import_json"]) if row["import_json"] else None}


# The import ----------------------------------------------------------------

def _write(planned: workbook.Planned) -> figures.FigureWrite:
    uuid, period, entity, dims = planned.key
    return figures.FigureWrite(uuid, period, entity, planned.value, [],
                               dimensions=json.loads(dims) if dims else None,
                               total="no_breakdown" if planned.total else None)


def import_at_confirm(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    """Import the starting workbook's figures against the confirmed setup, in the caller's transaction.
    Returns the import's summary, or None when the run has no starting workbook. Raises `workbook.Refused`.
    A workbook already imported is not imported again."""
    row = _row(conn, run_id)
    if row is None:
        return None
    if row["imported_at"]:
        return json.loads(row["import_json"])
    logger.info("Run %s: starting workbook import start.", run_id)
    try:
        path = path_of(conn, run_id)
        family = run_family(conn, run_id)
        setup = conn.execute("SELECT unit, year_end FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
        plan, said = workbook.plan_import(conn, family, str(path), dict(setup) if setup else {})
    except workbook.Refused as exc:
        logger.info("Run %s: starting workbook refused: %s", run_id, exc)
        raise
    # Totals first: a typed total then keeps its amount whatever its lines add up to.
    ordered = sorted(plan.figures, key=lambda p: not p.total)
    results = figures.import_figures(conn, run_id, [
        (_write(p), workbook.source_ref(row["sha256"], p.cell), p.origin) for p in ordered])
    refused = [{"cell": p.cell, "period": p.key[1], "entity_scope": p.key[2], "sentence": r["refused"]}
               for p, r in zip(ordered, results) if not r["ok"]]
    done = [p for p, r in zip(ordered, results) if r["ok"]]
    summary = {
        "prior_year": sum(p.origin == "prior_workbook" for p in done),
        "typed_this_year": sum(p.origin == "typed_in_workbook" for p in done),
        "typed_totals": sum(p.total for p in done),
        "not_imported": plan.not_imported + refused,
        "formulas_left": plan.formulas_left,
        "loose": plan.loose,
        "workbook": said,
    }
    stamp = db.now()
    conn.execute("UPDATE starting_workbooks SET imported_at = ?, import_json = ?, facts_json = ? WHERE run_id = ?",
                 (stamp, json.dumps(summary), json.dumps(said), run_id))
    events.insert(conn, SOURCE, "workbook_imported",
                  f"Imported {summary['prior_year']} of last year's figures (locked) and "
                  f"{summary['typed_this_year']} figures typed for this year (kept fixed) from the starting "
                  "workbook." + (f" {len(summary['not_imported'])} cell(s) were not imported."
                                 if summary["not_imported"] else ""),
                  run_id=run_id, data={k: (len(v) if isinstance(v, list) else v) for k, v in summary.items()
                                       if k != "workbook"} | {"sha256": row["sha256"]})
    for item in refused:
        logger.warning("Run %s: starting workbook cell %s not imported: %s", run_id, item["cell"], item["sentence"])
    logger.info("Run %s: starting workbook import end: %d last-year, %d typed this year, %d not imported.",
                run_id, summary["prior_year"], summary["typed_this_year"], len(summary["not_imported"]))
    return summary


def imported_cells(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """Every figure imported from the starting workbook, with the cell it came from: what the fill must
    leave unchanged (step 10g). A typed figure a person has since edited is listed too: its `origin` is then
    `person` and `person_edited` is true."""
    out = []
    for r in conn.execute(
            "SELECT id, concept_uuid, period, entity_scope, dimension_key, value, status, origin, locked, "
            "person_edited, source_ref FROM figures WHERE run_id = ? AND source_ref IS NOT NULL ORDER BY id",
            (run_id,)):
        try:
            ref = json.loads(r["source_ref"])
        except ValueError:
            continue   # not this workbook's form
        if not isinstance(ref, dict) or "cell" not in ref:
            continue
        out.append({"figure_id": r["id"], "key": (r["concept_uuid"], r["period"], r["entity_scope"],
                                                  r["dimension_key"]),
                    "value": None if r["status"] == "not_disclosed" else r["value"], "origin": r["origin"],
                    "locked": bool(r["locked"]), "person_edited": bool(r["person_edited"]),
                    "sha256": ref["sha256"], "cell": ref["cell"]})
    return out

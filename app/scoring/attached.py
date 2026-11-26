"""The workbook attached to a run, and its comparison with the run's current figures.

Rebuilt from v1 `eval/human_file.py` (`store_human_file`, `delete_rows`,
`load_human_file`) and `eval/human_compare.py` (`load_comparison`). v1 kept
only the cells it read; v2 also keeps the file, through the safe-path and
atomic-write helpers, so it can be read again when the run's templates
change (a statement's layout confirmed again after the workbook was attached).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from app import db
from app.catalog.lookup import RunFamily, run_family
from app.figures.sums import known_value
from app.scoring.compare import RunValue, compare
from app.catalog.fields import run_edges, run_fields
from app.scoring import workbook_notes
from app.scoring.workbook_read import PersonCell, Unread, WorkbookRead, read_filled_workbook
from app.utils.atomic_io import write_bytes_atomic
from app.utils.paths import output_dir, safe_entry_path, safe_path

logger = logging.getLogger(__name__)


class NoWorkbook(LookupError):
    """The run has no filled workbook attached."""


def _read_for(family: RunFamily) -> str:
    """What a stored read covers: the run's templates, and the notes. A workbook read before notes
    were read (no "notes" mark) is read again on its next comparison."""
    return json.dumps([*sorted(family.all_template_ids()), "notes"])


def _store(conn: sqlite3.Connection, run_id: int, read: WorkbookRead,
           notes: list[workbook_notes.WorkbookNote]) -> None:
    workbook_notes.store(conn, run_id, notes)
    conn.execute("DELETE FROM filled_workbook_cells WHERE run_id = ?", (run_id,))
    rows = [(run_id, *key, c.value, int(c.is_formula), c.workbook_cell, None, None, 0)
            for key, c in read.cells.items()]
    rows += [(run_id, *key, None, 0, u.workbook_cell, u.reason, u.sentence, int(u.holds_value))
             for key, u in read.unread.items()]
    conn.executemany(
        "INSERT INTO filled_workbook_cells(run_id, concept_uuid, period, entity_scope, dimension_key, value, "
        "is_formula, workbook_cell, unread_reason, unread_sentence, holds_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.execute("UPDATE filled_workbooks SET layout = ?, loose_json = ? WHERE run_id = ?",
                 (read.layout, json.dumps(read.loose), run_id))


def _stored_path(conn: sqlite3.Connection, run_id: int) -> Optional[str]:
    row = conn.execute("SELECT stored_path FROM filled_workbooks WHERE run_id = ?", (run_id,)).fetchone()
    return row[0] if row else None


def _discard(run_id: int, relative: str) -> None:
    """Delete a kept file the run no longer points at. A file that cannot be deleted is left and logged."""
    try:
        with db.connect() as conn:
            if _stored_path(conn, run_id) == relative:
                return
        safe_entry_path(output_dir() / relative).unlink(missing_ok=True)
    except (OSError, sqlite3.Error):
        logger.warning("Could not delete the unused workbook file %s of run %s.", relative, run_id, exc_info=True)


def attach(run_id: int, data: bytes, *, filename: str, uploaded_by: str) -> dict:
    """Keep the file and read it. A refused file leaves any earlier workbook as it was.

    The workbook is read before the write lock is taken, so figure saves are
    not held up. The previous file is deleted only after the save commits.
    Raises `xlsx_cells.WorkbookUnreadable` or `workbook_read.NothingMatches`."""
    sha = hashlib.sha256(data).hexdigest()
    relative = f"runs/run-{int(run_id)}/filled-workbook-{sha[:16]}.xlsx"
    path = write_bytes_atomic(output_dir() / relative, data)
    try:
        with db.connect() as conn:
            family = run_family(conn, run_id)
            read = read_filled_workbook(conn, family, str(path))
            notes = workbook_notes.read_filled_notes(conn, run_id, str(path))
        with db.connect(immediate=True) as conn:
            old = _stored_path(conn, run_id)
            conn.execute(
                "INSERT INTO filled_workbooks(run_id, filename, sha256, stored_path, layout, uploaded_by, "
                "uploaded_at, read_for) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                "filename = excluded.filename, sha256 = excluded.sha256, stored_path = excluded.stored_path, "
                "uploaded_by = excluded.uploaded_by, uploaded_at = excluded.uploaded_at, read_for = excluded.read_for",
                (run_id, Path(filename).name[:255] or "workbook.xlsx", sha, relative, read.layout, uploaded_by,
                 db.now(), _read_for(family)))
            _store(conn, run_id, read, notes)
            result = record(conn, run_id)
    except BaseException:
        _discard(run_id, relative)
        raise
    if old is not None and old != relative:
        _discard(run_id, old)
    return result


def remove(run_id: int) -> None:
    """Forget the run's workbook. The file is deleted once that has committed."""
    with db.connect(immediate=True) as conn:
        relative = _stored_path(conn, run_id)
        if relative is None:
            raise NoWorkbook("This run has no filled workbook.")
        conn.execute("DELETE FROM filled_workbook_cells WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM filled_workbook_notes WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM filled_workbooks WHERE run_id = ?", (run_id,))
    _discard(run_id, relative)


def record(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM filled_workbooks WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    counts = conn.execute(
        "SELECT SUM(unread_reason IS NULL), SUM(unread_reason IS NOT NULL AND holds_value = 1) "
        "FROM filled_workbook_cells WHERE run_id = ?", (run_id,)).fetchone()
    return {"filename": row["filename"], "sha256": row["sha256"], "layout": row["layout"],
            "uploaded_by": row["uploaded_by"], "uploaded_at": row["uploaded_at"],
            "cells_read": int(counts[0] or 0),
            "not_assessed": int(counts[1] or 0) + len(json.loads(row["loose_json"]))}


def person_cells(conn: sqlite3.Connection, run_id: int) -> tuple[dict, dict, list]:
    """The stored read: (cells, unread, loose)."""
    cells, unread = {}, {}
    for r in conn.execute("SELECT * FROM filled_workbook_cells WHERE run_id = ?", (run_id,)):
        key = (r["concept_uuid"], r["period"], r["entity_scope"], r["dimension_key"])
        if r["unread_reason"]:
            unread[key] = Unread(r["unread_reason"], r["unread_sentence"] or "", r["workbook_cell"],
                                 bool(r["holds_value"]))
        else:
            cells[key] = PersonCell(r["value"], bool(r["is_formula"]), r["workbook_cell"])
    row = conn.execute("SELECT loose_json FROM filled_workbooks WHERE run_id = ?", (run_id,)).fetchone()
    return cells, unread, json.loads(row[0]) if row else []


def run_values(conn: sqlite3.Connection, run_id: int) -> dict:
    return {(r["concept_uuid"], r["period"], r["entity_scope"], r["dimension_key"]):
            RunValue(known_value(r["value"], r["status"]), r["id"],
                     r["children_status"] == "aggregate_only" or r["origin"] == "typed_in_workbook")
            for r in conn.execute("SELECT id, concept_uuid, period, entity_scope, dimension_key, value, status, "
                                  "children_status, origin FROM figures WHERE run_id = ?", (run_id,))}


def score(conn: sqlite3.Connection, family: RunFamily, read: WorkbookRead) -> dict:
    """The comparison of a workbook's read with the run's current figures."""
    return compare(run_fields(conn, family), read.cells, read.unread, read.loose,
                   run_values(conn, family.run_id), run_edges(conn, family), periods=family.periods)


def comparison(run_id: int) -> dict:
    """The comparison with the run's current figures and notes. Raises NoWorkbook.

    When the run's templates changed since the workbook was read, it is read
    again outside the write lock, then stored in a short write that checks it
    is still needed."""
    with db.connect() as conn:
        row = conn.execute("SELECT stored_path, read_for FROM filled_workbooks WHERE run_id = ?",
                           (run_id,)).fetchone()
        if row is None:
            raise NoWorkbook("This run has no filled workbook.")
        family = run_family(conn, run_id)
    read_for = _read_for(family)
    if row["read_for"] != read_for:   # the run's templates changed since the workbook was read
        with db.connect() as conn:    # reads only; the file is parsed before its first query
            path = str(safe_path(output_dir() / row["stored_path"]))
            read = read_filled_workbook(conn, family, path)
            notes = workbook_notes.read_filled_notes(conn, run_id, path)
        with db.connect(immediate=True) as conn:
            current = conn.execute("SELECT stored_path, read_for FROM filled_workbooks WHERE run_id = ?",
                                   (run_id,)).fetchone()
            still_stale = (current is not None and current["stored_path"] == row["stored_path"]
                           and current["read_for"] != read_for
                           and _read_for(run_family(conn, run_id)) == read_for)
            if still_stale:
                _store(conn, run_id, read, notes)
                conn.execute("UPDATE filled_workbooks SET read_for = ? WHERE run_id = ?", (read_for, run_id))
    with db.connect() as conn:
        workbook = record(conn, run_id)
        if workbook is None:
            raise NoWorkbook("This run has no filled workbook.")
        cells, unread, loose = person_cells(conn, run_id)
        result = score(conn, run_family(conn, run_id), WorkbookRead(workbook["layout"], cells, unread, loose))
        notes_result = workbook_notes.comparison(conn, run_id)
    return {"workbook": workbook, **result, "notes": notes_result}

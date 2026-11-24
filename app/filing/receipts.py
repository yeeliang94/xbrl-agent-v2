"""The `fills` table: one row per mTool fill, from upload to receipt
(docs/api-contract.md, Step 8 and Step 10g).

`start` keeps the uploaded template in the run's folder and queues the
`fill` job in one transaction. A run with a starting workbook takes no
upload: `start_from_starting` queues the fill of that workbook, whose kept
file is the row's template. The job (`app/filing/job.py`) moves the row
queued -> filling -> ready or failed. The uploaded template is never
changed; the filled file is a new file beside it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

from app import db
from app.filing.mappings import key as figure_key
from app.jobs import queue
from app.runs import status as run_status
from app.utils.atomic_io import write_bytes_atomic
from app.utils.paths import output_dir, safe_path

JOB = "fill"
SOURCE = "fill"
SUFFIXES = (".xlsx", ".xlsm")
ACTIVE = ("queued", "filling")

WRONG_TYPE = "Choose an .xlsx or .xlsm mTool template."
ALREADY_FILLING = "A fill is already running for this run."
BUSY = "The run is still working, so prepare the mTool file when it finishes."
NOT_SET_UP = "Confirm the run's setup before preparing the mTool file."
NOT_READY = "This mTool file is not ready yet."
NO_FILE = "The filled file is no longer on the server, so fill the template again."
HAS_STARTING = ("This run fills the workbook attached at setup, so prepare the mTool file without uploading "
                "a template.")
# A run in one of these has an agent queued or working.
BUSY_STATUSES = (run_status.READING, run_status.READY, run_status.EXTRACTING, run_status.NEEDS_ANSWER,
                 run_status.CORRECTING)


class FillRefused(ValueError):
    def __init__(self, sentence: str, status: int = 409) -> None:
        super().__init__(sentence)
        self.status = status


def folder(run_id: int) -> str:
    """The run's fill folder, relative to the output folder, named from its number alone."""
    return f"runs/run-{int(run_id)}/fills"


def file_path(relative: Optional[str]) -> Optional[Path]:
    """A stored relative path as a checked absolute path, or None."""
    return safe_path(output_dir() / relative) if relative else None


def _refuse_if_busy(conn: sqlite3.Connection, run: sqlite3.Row) -> None:
    if run["status"] == run_status.SETUP:
        raise FillRefused(NOT_SET_UP)
    if run["status"] in BUSY_STATUSES:
        raise FillRefused(BUSY)
    if conn.execute("SELECT 1 FROM fills WHERE run_id = ? AND job_status IN ('queued', 'filling')",
                    (run["id"],)).fetchone():
        raise FillRefused(ALREADY_FILLING)
    # A search for places in a filled template (step 12) changes no figure, so it never makes the run busy.
    other = conn.execute("SELECT 1 FROM jobs WHERE run_id = ? AND kind NOT IN (?, 'investigate') AND status IN "
                         "('queued', 'working', 'retry')", (run["id"], JOB)).fetchone()
    if other is not None:
        raise FillRefused(BUSY)


def start(conn: sqlite3.Connection, run: sqlite3.Row, data: bytes, *, filename: str, email: str) -> sqlite3.Row:
    """Keep the template and queue its fill. Use inside `db.connect(immediate=True)`. Raises FillRefused."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        raise FillRefused(WRONG_TYPE, 422)
    if conn.execute("SELECT 1 FROM starting_workbooks WHERE run_id = ?", (run["id"],)).fetchone():
        raise FillRefused(HAS_STARTING)
    _refuse_if_busy(conn, run)
    run_id, stamp = int(run["id"]), db.now()
    try:
        fill_id = int(conn.execute(
            "INSERT INTO fills(run_id, created_by, created_at, template_filename, template_path, template_sha256) "
            "VALUES (?, ?, ?, ?, '', ?)",
            (run_id, email, stamp, filename, hashlib.sha256(data).hexdigest())).lastrowid)
    except sqlite3.IntegrityError as exc:   # the one-active-fill index: a second upload raced this one
        raise FillRefused(ALREADY_FILLING) from exc
    template = f"{folder(run_id)}/template-{fill_id}{suffix}"
    write_bytes_atomic(output_dir() / template, data)
    job_id = queue.enqueue_in(conn, JOB, {"fill_id": fill_id}, max_attempts=1, run_id=run_id)
    conn.execute("UPDATE fills SET template_path = ?, job_id = ? WHERE id = ?", (template, job_id, fill_id))
    conn.execute("INSERT INTO events(run_id, job_id, source, kind, message, data_json, created_at) "
                 "VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                 (run_id, job_id, SOURCE, "The mTool fill is queued.", json.dumps({"fill_id": fill_id}), stamp))
    return get_row(conn, run_id, fill_id)


def start_from_starting(conn: sqlite3.Connection, run: sqlite3.Row, *, email: str) -> sqlite3.Row:
    """Queue the fill of the run's starting workbook (step 10g). The fill writes into a copy of that file,
    never a template a person uploads. Use inside `db.connect(immediate=True)`. Raises FillRefused."""
    _refuse_if_busy(conn, run)
    start = conn.execute("SELECT filename, sha256, stored_path FROM starting_workbooks WHERE run_id = ?",
                         (run["id"],)).fetchone()
    if start is None:
        raise FillRefused(WRONG_TYPE, 422)
    run_id, stamp = int(run["id"]), db.now()
    try:
        fill_id = int(conn.execute(
            "INSERT INTO fills(run_id, created_by, created_at, template_filename, template_path, template_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, email, stamp, start["filename"], start["stored_path"], start["sha256"])).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise FillRefused(ALREADY_FILLING) from exc
    job_id = queue.enqueue_in(conn, JOB, {"fill_id": fill_id}, max_attempts=1, run_id=run_id)
    conn.execute("UPDATE fills SET job_id = ? WHERE id = ?", (job_id, fill_id))
    conn.execute("INSERT INTO events(run_id, job_id, source, kind, message, data_json, created_at) "
                 "VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                 (run_id, job_id, SOURCE, "The mTool fill of the starting workbook is queued.",
                  json.dumps({"fill_id": fill_id, "starting_workbook": True}), stamp))
    return get_row(conn, run_id, fill_id)


def start_again(conn: sqlite3.Connection, run: sqlite3.Row, fill: sqlite3.Row, *, email: str) -> sqlite3.Row:
    """Queue a new fill of the same template as `fill`, after a person saved places for it (step 12). The
    kept template file is reused; it is never changed. Use inside `db.connect(immediate=True)`."""
    if conn.execute("SELECT 1 FROM starting_workbooks WHERE run_id = ?", (run["id"],)).fetchone():
        return start_from_starting(conn, run, email=email)
    _refuse_if_busy(conn, run)
    run_id, stamp = int(run["id"]), db.now()
    try:
        fill_id = int(conn.execute(
            "INSERT INTO fills(run_id, created_by, created_at, template_filename, template_path, template_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, email, stamp, fill["template_filename"], fill["template_path"], fill["template_sha256"])).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise FillRefused(ALREADY_FILLING) from exc
    job_id = queue.enqueue_in(conn, JOB, {"fill_id": fill_id}, max_attempts=1, run_id=run_id)
    conn.execute("UPDATE fills SET job_id = ? WHERE id = ?", (job_id, fill_id))
    conn.execute("INSERT INTO events(run_id, job_id, source, kind, message, data_json, created_at) "
                 "VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                 (run_id, job_id, SOURCE, "The mTool fill is queued again with the places a person checked.",
                  json.dumps({"fill_id": fill_id, "after": int(fill["id"])}), stamp))
    return get_row(conn, run_id, fill_id)


def get_row(conn: sqlite3.Connection, run_id: int, fill_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM fills WHERE run_id = ? AND id = ?", (run_id, fill_id)).fetchone()
    if row is None:
        raise FillRefused("There is no such fill in this run.", 404)
    return row


def _line_id(kind: str, line: dict) -> str:
    """Stable and unique within a receipt: the figure's key (the note field, the report field or the
    workbook cell) and the line's kind."""
    if line.get("element_id") is not None:
        return f"{kind}|{line['report']}|{line['element_id'] or line.get('field_id')}"
    if line.get("field_id") is not None:
        return f"{kind}|{line['field_id']}"
    if line.get("workbook_cell") and not line.get("concept_uuid"):
        return f"{kind}|{line['workbook_cell']}"
    return "|".join([kind, *(str(line.get(k) or "") for k in ("concept_uuid", "period", "entity_scope", "dimension_key"))])


def _lines(kind: str, lines: list) -> list[dict]:
    return [{"id": _line_id(kind, line), "kind": kind, "name": line.get("name") or line.get("field") or "A figure",
             "reason": line.get("reason", ""), "code": line.get("code")} for line in lines or []
            if line.get("code") not in EXPECTED]


# What the receipt counts and lists as not written. `kept` lines are left out: the template works
# those totals out with its own formula, as expected, so they are neither listed nor counted.
NOT_WRITTEN = ("unresolved", "mismatched", "skipped")
# Skipped on purpose and expected on every fill, so not listed or counted either: the share-capital
# and related-party notes file the current year only (owner, 23 November 2026). They stay in report_json.
EXPECTED = frozenset({"current_year_only"})


NOT_FOUND = "No place found in this template."


def receipt(report: dict, not_found: frozenset = frozenset()) -> dict:
    """What a person reads: the counts and every line not written, by name and reason. No cell address.
    A fill into a starting workbook also lists the workbook's values it kept and the person's edits that
    replaced a typed figure; the imported figures it kept are counted, not listed. `not_found` holds the
    figures the investigating agent looked for and found no place for (step 12): their reason says so."""
    if not_found:
        report = {**report, **{k: [{**line, "reason": NOT_FOUND} if figure_key(line) in not_found else line
                                   for line in report.get(k) or []] for k in ("unresolved", "mismatched")}}
    notes = report.get("notes") or {}
    reports = report.get("reports") or {}
    starting = report.get("starting") or {}
    lines: list[dict] = []   # what needs a person first, then what was left out on purpose
    for key in NOT_WRITTEN:
        lines += _lines(key, report.get(key))
    for key in NOT_WRITTEN:
        lines += _lines(f"note_{key}", notes.get(key))
    for key in ("unresolved", "mismatched", "skipped"):
        lines += _lines(f"report_{key}", reports.get(key))
    lines += _lines("workbook_kept", starting.get("workbook_kept"))
    lines += _lines("prior_year_added", starting.get("prior_year_added"))
    lines += _lines("replaced", starting.get("replaced"))
    counts = report.get("counts") or {}
    template = report.get("template") or {}
    return {"counts": {"written": counts.get("written", 0),
                       "not_written": sum(1 for line in lines if line["kind"] in NOT_WRITTEN),
                       "notes": counts.get("notes_written", 0),
                       "notes_not_written": counts.get("notes_not_written", 0),
                       "reports": counts.get("reports_written", 0),
                       "reports_not_written": counts.get("reports_not_written", 0),
                       "kept_in_workbook": counts.get("kept_in_workbook", 0),
                       "workbook_kept": counts.get("workbook_kept", 0)},
            "lines": lines,
            "template": {"name": template.get("name"), "compatibility": template.get("compatibility"),
                         "reasons": template.get("reasons") or []}}


def public(row: sqlite3.Row, *, with_receipt: bool = False, not_found: frozenset = frozenset(),
           placements_open: Optional[int] = None) -> dict:
    """`Fill` (docs/api-contract.md, Step 8 and Step 12). No file path leaves the server. `not_found` and
    `placements_open` come from the investigation's own store (step 12), read by the route."""
    out = {"id": row["id"], "run_id": row["run_id"], "job_status": row["job_status"], "error": row["error"],
           "template_filename": row["template_filename"], "template_sha256": row["template_sha256"],
           "compatibility": row["compatibility"], "status": row["status"], "output_sha256": row["output_sha256"],
           "created_by": row["created_by"], "created_at": row["created_at"], "started_at": row["started_at"],
           "finished_at": row["finished_at"], "downloaded_at": row["downloaded_at"],
           "investigation": row["investigation"], "investigation_error": row["investigation_error"]}
    if with_receipt:
        report = json.loads(row["report_json"]) if row["report_json"] else None
        out["receipt"] = receipt(report, not_found) if report else None
    if placements_open is not None:
        out["placements_open"] = placements_open
    return out


_LIST_COLUMNS = ("id, run_id, job_status, error, template_filename, template_sha256, compatibility, status, "
                 "output_sha256, created_by, created_at, started_at, finished_at, downloaded_at, investigation, "
                 "investigation_error")


def list_fills(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """The run's fills, oldest first, without their receipts (the report is not read)."""
    return [public(r) for r in conn.execute(f"SELECT {_LIST_COLUMNS} FROM fills WHERE run_id = ? ORDER BY id",
                                            (run_id,))]


def download_name(row: sqlite3.Row) -> str:
    stem = Path(row["template_filename"]).stem or "mTool"
    return f"{stem} filled{Path(row['output_path']).suffix}"


def mark_downloaded(conn: sqlite3.Connection, run_id: int, fill_id: int) -> tuple[sqlite3.Row, Path]:
    """The ready fill and its file, marked downloaded. Raises FillRefused."""
    row = get_row(conn, run_id, fill_id)
    if row["job_status"] != "ready" or not row["output_path"]:
        raise FillRefused(NOT_READY)
    path = file_path(row["output_path"])
    if path is None or not path.is_relative_to(safe_path(output_dir() / folder(run_id))) or not path.is_file():
        raise FillRefused(NO_FILE, 410)
    conn.execute("UPDATE fills SET downloaded_at = ? WHERE id = ?", (db.now(), fill_id))
    return row, path


# The job's writes ---------------------------------------------------------------

def begin(fill_id: int) -> Optional[sqlite3.Row]:
    """Mark a waiting fill filling. None when it has ended already."""
    with db.connect(immediate=True) as conn:
        row = conn.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone()
        if row is None or row["job_status"] not in ACTIVE:
            return None
        conn.execute("UPDATE fills SET job_status = 'filling', started_at = ?, error = NULL WHERE id = ?",
                     (db.now(), fill_id))
        return conn.execute("SELECT * FROM fills WHERE id = ?", (fill_id,)).fetchone()


def finish(fill_id: int, report: dict, output_relative: str) -> None:
    template = report["template"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE fills SET job_status = 'ready', template_fingerprint = ?, compatibility = ?, figures_digest = ?, "
            "notes_digest = ?, output_path = ?, output_sha256 = ?, status = ?, report_json = ?, finished_at = ? "
            "WHERE id = ?",
            (template["fingerprint"], template["compatibility"], report["figures_digest"], report["notes_digest"],
             output_relative, report["output"]["sha256"], report["status"],
             json.dumps({**report, "output": {"path": output_relative, "sha256": report["output"]["sha256"]}},
                        default=str),
             db.now(), fill_id))


def failed(fill_id: int, sentence: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE fills SET job_status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                     (sentence, db.now(), fill_id))

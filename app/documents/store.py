"""A run's document: create a run from an uploaded file, and read it back.

The run's PDF (the upload, or the reading copy of a Word or Excel file) and
the uploaded file are kept in the run's folder through the safe-path helpers
and an atomic write. A `documents` row and one `pages` row per page are
written in the same transaction as the run, so a failure leaves no half-made
run.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

from app.db import now
from app.documents import file_lines
from app.documents.intake import Prepared
from app.documents.pdf_check import PageFacts
from app.documents.reading_copy import REDRAW
from app.documents.source_file import EXCEL, PDF, WORD
from app.runs import status as run_status, store as runs
from app.utils.atomic_io import write_bytes_atomic
from app.utils.paths import output_dir, safe_path


class NoDocument(LookupError):
    """The run has no uploaded document."""

    def __init__(self) -> None:
        super().__init__("This run has no document.")


def create_run_from_pdf(conn: sqlite3.Connection, data: bytes, pages: list[PageFacts], *,
                        filename: str, owner_email: str) -> int:
    """A new run in `reading` with its PDF stored. `pages` comes from
    `pdf_check.inspect_pdf(data)`. Use inside `db.connect(immediate=True)`."""
    return create_run(conn, Prepared(PDF, filename, data, data, pages), owner_email=owner_email)


def _counted(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def _stored_message(upload: Prepared) -> str:
    count = len(upload.pages)
    if upload.kind == PDF:
        scanned = sum(not p.has_text_layer for p in upload.pages)
        return f"The PDF is stored: {count} pages, {scanned} of them scanned."
    if upload.kind == EXCEL:
        used = sum(s["used"] for s in upload.sheets or [])
        left_out = sum(s["hidden"] and not s["used"] for s in upload.sheets or [])
        hidden = f"; {_counted(left_out, 'hidden sheet')} left out" if left_out else ""
        return (f"The Excel workbook is stored and its reading copy is made: {_counted(count, 'page')} from "
                f"{_counted(used, 'sheet')}{hidden}.")
    return f"The Word file is stored and its reading copy is made: {_counted(count, 'page')}."


def write_files(run_id: int, upload: Prepared) -> tuple[str, Optional[str]]:
    """Keep the run's PDF, and the uploaded Word or Excel file beside it. Returns their stored paths."""
    folder = f"runs/run-{int(run_id)}"
    relative = f"{folder}/document-{hashlib.sha256(upload.pdf).hexdigest()[:16]}.pdf"
    write_bytes_atomic(output_dir() / relative, upload.pdf)
    if upload.kind == PDF:
        return relative, None
    suffix = "docx" if upload.kind == WORD else "xlsx"
    source = f"{folder}/source-{hashlib.sha256(upload.data).hexdigest()[:16]}.{suffix}"
    write_bytes_atomic(output_dir() / source, upload.data)
    return relative, source


def add_pages(conn: sqlite3.Connection, document_id: int, pages: list[PageFacts]) -> None:
    conn.executemany(
        "INSERT INTO pages(document_id, page, width, height, rotation, has_text_layer) VALUES (?, ?, ?, ?, ?, ?)",
        [(document_id, p.page, p.width, p.height, p.rotation, int(p.has_text_layer)) for p in pages])


def create_run(conn: sqlite3.Connection, upload: Prepared, *, owner_email: str) -> int:
    """A new run in `reading` from a checked upload (`intake.prepare`). Its PDF (the upload itself, or
    the reading copy of a Word or Excel file) and the uploaded file are stored, with a `documents`
    row, a `pages` row per page and the file's own lines. Use inside `db.connect(immediate=True)`."""
    run_id = runs.create_reading_run(conn, owner_email=owner_email)
    relative, source = write_files(run_id, upload)
    stamp = now()
    document_id = int(conn.execute(
        "INSERT INTO documents(run_id, filename, stored_path, sha256, size_bytes, page_count, uploaded_by, "
        "uploaded_at, kind, source_path, source_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, upload.filename, relative, hashlib.sha256(upload.data).hexdigest(), len(upload.data),
         len(upload.pages), owner_email, stamp, upload.kind, source,
         json.dumps({"sheets": upload.sheets}, ensure_ascii=False) if upload.sheets is not None else None)
    ).lastrowid)
    add_pages(conn, document_id, upload.pages)
    file_lines.save(conn, document_id, upload.lines)
    conn.execute("INSERT INTO stages(run_id, name, status, started_at, finished_at) VALUES (?, 'upload', 'done', ?, ?)",
                 (run_id, stamp, stamp))
    conn.execute(
        "INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, 'upload', 'finished', ?, ?)",
        (run_id, _stored_message(upload), stamp))
    notices = [sheet_notice(sheet) for sheet in upload.sheets or []] + [_word_notice(upload.pictures_not_drawn)]
    for notice in filter(None, notices):
        conn.execute(
            "INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, 'upload', 'notice', ?, ?)",
            (run_id, notice, stamp))
    start_reading(conn, run_id)
    return run_id


def sheet_notice(sheet: dict) -> Optional[str]:
    """What a person is told about a sheet the reading copy shows only in part: formulas Excel saved
    without a result, and pictures in a format the reading copy cannot draw. None when there is neither."""
    out = []
    if count := sheet.get("empty_formulas", 0):
        out.append(f"The sheet {sheet['name']} has {_counted(count, 'formula')} saved without a result, so "
                   f"{'they read' if count != 1 else 'it reads'} as empty. Open the workbook in Excel, save it "
                   "and upload it again.")
    if count := sheet.get("pictures_not_drawn", 0):
        out.append(f"The sheet {sheet['name']} has {_not_drawn(count)} upload the workbook again.")
    return " ".join(out) or None


def _word_notice(count: int) -> Optional[str]:
    return f"The Word file has {_not_drawn(count)} upload it again." if count else None


def _not_drawn(count: int) -> str:
    return (f"{_counted(count, 'picture')} saved in a format the reading copy cannot draw, so "
            f"{'they are' if count != 1 else 'it is'} not shown. {REDRAW}")


READ_JOB = "read"


def start_reading(conn: sqlite3.Connection, run_id: int) -> int:
    """The one place a run's reading starts: the `read` stage waits and the
    Reader's job is queued, linked to it. A retry reuses the same stage row
    (v1 once made a second one). Returns the job id."""
    from app.jobs import queue

    row = conn.execute("SELECT id FROM stages WHERE run_id = ? AND name = 'read'", (run_id,)).fetchone()
    if row is None:
        stage_id = int(conn.execute("INSERT INTO stages(run_id, name, status) VALUES (?, 'read', 'waiting')",
                                    (run_id,)).lastrowid)
    else:
        stage_id = int(row["id"])
        conn.execute("UPDATE stages SET status = 'waiting', started_at = NULL, finished_at = NULL, error = NULL, "
                     "stop_requested = 0 WHERE id = ?", (stage_id,))
        run_status.reading_started(conn, run_id)
    # One attempt: a failure waits for a person's retry instead of spending
    # again by itself. A server restart still hands the job back once.
    return queue.enqueue_in(conn, READ_JOB, {}, max_attempts=1, run_id=run_id, stage_id=stage_id)


def document_row(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise NoDocument()
    return row


def sheets(row: sqlite3.Row) -> list[dict]:
    """An Excel run's sheets (`workbook_copy.workbook_copy`), in the workbook's order; [] for any other run."""
    return (json.loads(row["source_json"]).get("sheets") or []) if row["source_json"] else []


def document(conn: sqlite3.Connection, run_id: int) -> dict:
    """The run's `Document` (docs/api-contract.md, Step 3), or NoDocument."""
    row = document_row(conn, run_id)
    pages = [{"page": p["page"], "width": p["width"], "height": p["height"], "rotation": p["rotation"],
              "has_text_layer": bool(p["has_text_layer"])}
             for p in conn.execute("SELECT * FROM pages WHERE document_id = ? ORDER BY page", (row["id"],))]
    out = {"filename": row["filename"], "kind": row["kind"], "sha256": row["sha256"],
           "size_bytes": row["size_bytes"], "page_count": row["page_count"],
           "scanned_pages": sum(not p["has_text_layer"] for p in pages),
           "uploaded_by": row["uploaded_by"], "uploaded_at": row["uploaded_at"], "pages": pages}
    if row["kind"] == EXCEL:
        out["sheets"] = [{**s, "notice": sheet_notice(s)} for s in sheets(row)]
    return out


def pdf_path(conn: sqlite3.Connection, run_id: int) -> tuple[Path, int]:
    """The stored PDF's path and its page count, or NoDocument."""
    row = document_row(conn, run_id)
    return safe_path(output_dir() / row["stored_path"]), int(row["page_count"])


def upright_turn(conn: sqlite3.Connection, run_id: int, page: int) -> int:
    """The clockwise turn that makes a page upright, beyond the PDF's own
    rotation, as the Reader recorded it (`MapPage.rotation`). 0 for a page not
    read yet."""
    row = conn.execute(
        "SELECT json_extract(p.content_json, '$.rotation') FROM pages p JOIN documents d ON d.id = p.document_id "
        "WHERE d.run_id = ? AND p.page = ?", (run_id, page)).fetchone()
    turn = int(row[0] or 0) if row is not None else 0
    return turn if turn in (0, 90, 180, 270) else 0

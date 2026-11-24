"""A run's document: create a run from an uploaded PDF, and read it back.

The PDF is kept in the run's folder through the safe-path helpers and an
atomic write. A `documents` row and one `pages` row per page are written in
the same transaction as the run, so a failure leaves no half-made run.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from app.db import now
from app.documents.pdf_check import PageFacts
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
    run_id = runs.create_reading_run(conn, owner_email=owner_email)
    sha = hashlib.sha256(data).hexdigest()
    relative = f"runs/run-{int(run_id)}/document-{sha[:16]}.pdf"
    write_bytes_atomic(output_dir() / relative, data)
    stamp = now()
    document_id = int(conn.execute(
        "INSERT INTO documents(run_id, filename, stored_path, sha256, size_bytes, page_count, uploaded_by, "
        "uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, filename, relative, sha, len(data), len(pages), owner_email, stamp)).lastrowid)
    conn.executemany(
        "INSERT INTO pages(document_id, page, width, height, rotation, has_text_layer) VALUES (?, ?, ?, ?, ?, ?)",
        [(document_id, p.page, p.width, p.height, p.rotation, int(p.has_text_layer)) for p in pages])
    conn.execute("INSERT INTO stages(run_id, name, status, started_at, finished_at) VALUES (?, 'upload', 'done', ?, ?)",
                 (run_id, stamp, stamp))
    scanned = sum(not p.has_text_layer for p in pages)
    conn.execute(
        "INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, 'upload', 'finished', ?, ?)",
        (run_id, f"The PDF is stored: {len(pages)} pages, {scanned} of them scanned.", stamp))
    start_reading(conn, run_id)
    return run_id


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
        conn.execute("UPDATE stages SET status = 'waiting', started_at = NULL, finished_at = NULL, error = NULL "
                     "WHERE id = ?", (stage_id,))
        run_status.reading_started(conn, run_id)
    # One attempt: a failure waits for a person's retry instead of spending
    # again by itself. A server restart still hands the job back once.
    return queue.enqueue_in(conn, READ_JOB, {}, max_attempts=1, run_id=run_id, stage_id=stage_id)


def document_row(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise NoDocument()
    return row


def document(conn: sqlite3.Connection, run_id: int) -> dict:
    """The run's `Document` (docs/api-contract.md, Step 3), or NoDocument."""
    row = document_row(conn, run_id)
    pages = [{"page": p["page"], "width": p["width"], "height": p["height"], "rotation": p["rotation"],
              "has_text_layer": bool(p["has_text_layer"])}
             for p in conn.execute("SELECT * FROM pages WHERE document_id = ? ORDER BY page", (row["id"],))]
    return {"filename": row["filename"], "sha256": row["sha256"], "size_bytes": row["size_bytes"],
            "page_count": row["page_count"], "scanned_pages": sum(not p["has_text_layer"] for p in pages),
            "uploaded_by": row["uploaded_by"], "uploaded_at": row["uploaded_at"], "pages": pages}


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

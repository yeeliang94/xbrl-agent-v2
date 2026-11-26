"""The only code that reads or writes the `issues` table and the issue folders.

A report keeps the number of the run that was on screen and that run's name
as it was then, so the list still reads well after the run is deleted. Its
screenshot sits in `<output folder>/issues/issue-<id>/` under a name the
server chose.
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
from pathlib import Path
from typing import Optional

from app.db import now
from app.utils.atomic_io import write_bytes_atomic
from app.utils.paths import output_dir, safe_entry_path, safe_path

logger = logging.getLogger(__name__)

STATUSES = ("open", "closed")
# A screenshot is told by its first bytes, never by its name.
_PICTURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)

_SQL = ("SELECT i.*, u.name AS reporter_name FROM issues i LEFT JOIN users u ON u.email = i.reporter_email")


def picture_kind(data: bytes) -> Optional[tuple[str, str]]:
    """(file ending, media type) when the bytes are a PNG, JPEG, GIF or WebP picture, else None."""
    for start, ending, media in _PICTURES:
        if data.startswith(start):
            return ending, media
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _issue(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "reporter_email": row["reporter_email"],
        "reporter_name": row["reporter_name"] or "",
        "text": row["text"],
        "run_id": row["run_id"],
        "run_label": row["run_label"],
        "status": row["status"],
        "note": row["note"],
        "file_name": row["file_name"],
    }


def folder(issue_id: int) -> Path:
    """The issue's own folder, named from its number alone."""
    return safe_path(output_dir() / "issues" / f"issue-{int(issue_id)}")


def create(conn: sqlite3.Connection, *, reporter_email: str, text: str, run_id: Optional[int], run_label: str,
           file_name: Optional[str] = None, file_data: Optional[bytes] = None) -> dict:
    """Save a report and, when given, its screenshot. Use inside `db.connect(immediate=True)`."""
    stamp = now()
    issue_id = int(conn.execute(
        "INSERT INTO issues(reporter_email, text, run_id, run_label, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", (reporter_email, text, run_id, run_label, stamp, stamp)).lastrowid)
    if file_data is not None:
        ending = (picture_kind(file_data) or ("bin", ""))[0]
        stored = write_bytes_atomic(folder(issue_id) / f"screenshot-{secrets.token_hex(8)}.{ending}", file_data)
        conn.execute("UPDATE issues SET file_name = ?, file_path = ? WHERE id = ?",
                     (file_name or f"screenshot.{ending}", stored.relative_to(output_dir()).as_posix(), issue_id))
    return get(conn, issue_id)


def get(conn: sqlite3.Connection, issue_id: int) -> Optional[dict]:
    row = conn.execute(_SQL + " WHERE i.id = ?", (issue_id,)).fetchone()
    return _issue(row) if row else None


def list_issues(conn: sqlite3.Connection, status: Optional[str] = None) -> list[dict]:
    """Newest first. `status` is `open`, `closed` or None for every issue."""
    if status in STATUSES:
        rows = conn.execute(_SQL + " WHERE i.status = ? ORDER BY i.id DESC", (status,))
    else:
        rows = conn.execute(_SQL + " ORDER BY i.id DESC")
    return [_issue(r) for r in rows]


def update(conn: sqlite3.Connection, issue_id: int, *, status: Optional[str] = None,
           note: Optional[str] = None) -> None:
    current = conn.execute("SELECT status, note FROM issues WHERE id = ?", (issue_id,)).fetchone()
    conn.execute("UPDATE issues SET status = ?, note = ?, updated_at = ? WHERE id = ?",
                 (status if status is not None else current["status"],
                  note if note is not None else current["note"], now(), issue_id))


def file_of(conn: sqlite3.Connection, issue_id: int) -> Optional[tuple[Path, str]]:
    """The screenshot's path and its name as uploaded, or None. A stored path
    that does not resolve inside the issue's own folder is ignored."""
    row = conn.execute("SELECT file_name, file_path FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None or not row["file_path"]:
        return None
    try:
        path = safe_path(output_dir() / row["file_path"])
    except PermissionError:
        return None
    if not path.is_relative_to(folder(issue_id)) or not path.is_file():
        return None
    return path, row["file_name"] or path.name


def delete(conn: sqlite3.Connection, issue_id: int) -> None:
    conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))


def remove_files(issue_id: int) -> None:
    """Remove the issue's folder. A symbolic link is removed itself, never
    followed. What cannot be removed is logged and left."""
    home = folder(issue_id)
    if not home.is_dir():
        return
    try:
        for entry in home.iterdir():
            safe_entry_path(entry).unlink()
        home.rmdir()
    except OSError:
        logger.warning("Issue %s: could not remove its files.", issue_id, exc_info=True)

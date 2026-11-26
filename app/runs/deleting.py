"""Deleting a run, and clearing abandoned drafts.

Who may delete: the run's owner and admins (go-live plan A4), checked here on
the server. What may be deleted: any run that is not working. A run is
working while it is being read, extracted or corrected, or while any job of
its own is queued or running (a fill, say).

A delete removes every row that belongs to the run (the tables cascade from
`runs`: figures, notes, comments, rounds, fills, traces) and writes an audit
row. The caller then removes the run's files with `store.remove_run_files`,
once the delete has committed.

An abandoned draft is a run still waiting at setup that nobody has touched
for a chosen number of days. Only an admin clears them.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from app.auth import store as auth_store
from app.auth.store import User
from app.runs import status as run_status
from app.runs.listing import WORKING

logger = logging.getLogger(__name__)

STILL_WORKING = "This run is still working, so stop it or wait until it finishes, then delete it."
NOT_YOURS = "Only the run's owner or an admin can delete this run."
MAX_DRAFT_DAYS = 3650


class DeleteRefused(ValueError):
    """The run stays. `str()` is one plain sentence; `code` is "owner" or "working"."""

    def __init__(self, code: str, sentence: str, status: int) -> None:
        super().__init__(sentence)
        self.code, self.status = code, status


def _busy(conn: sqlite3.Connection, run: sqlite3.Row) -> bool:
    return run["status"] in WORKING or conn.execute(
        "SELECT 1 FROM jobs WHERE run_id = ? AND status IN ('queued', 'working', 'retry')",
        (run["id"],)).fetchone() is not None


def check(conn: sqlite3.Connection, run: sqlite3.Row, user: User) -> None:
    """Raises DeleteRefused unless this person may delete this run now."""
    if not user.is_admin and run["owner_email"] != user.email:
        raise DeleteRefused("owner", NOT_YOURS, 403)
    if _busy(conn, run):
        raise DeleteRefused("working", STILL_WORKING, 409)


def contents(conn: sqlite3.Connection, run_id: int) -> dict:
    """What a delete removes, for the confirm dialog to name. Totals the app adds up are not counted as figures."""
    figures = conn.execute(
        "SELECT COUNT(*) FROM figures WHERE run_id = ? AND origin != 'calculated' AND "
        "((value IS NOT NULL AND status != 'not_disclosed') OR stated_value IS NOT NULL)", (run_id,)).fetchone()[0]
    notes = conn.execute("SELECT COUNT(*) FROM notes WHERE run_id = ?", (run_id,)).fetchone()[0]
    filled = conn.execute("SELECT 1 FROM fills WHERE run_id = ? LIMIT 1", (run_id,)).fetchone() is not None
    return {"figures": int(figures), "notes": int(notes), "filled_workbook": filled}


def _details(conn: sqlite3.Connection, run: sqlite3.Row) -> dict:
    company = conn.execute("SELECT name FROM companies WHERE id = ?", (run["company_id"],)).fetchone()
    document = conn.execute("SELECT filename FROM documents WHERE run_id = ?", (run["id"],)).fetchone()
    return {"run_id": int(run["id"]), "company": company["name"] if company else None,
            "filename": document["filename"] if document else None, "status": run["status"],
            "owner_email": run["owner_email"]}


def delete_run(conn: sqlite3.Connection, run: sqlite3.Row, user: User) -> None:
    """Delete the run's rows and write the audit row. Use inside
    `db.connect(immediate=True)`, then `store.remove_run_files`. Raises DeleteRefused."""
    check(conn, run, user)
    auth_store.add_audit(conn, user.email, "run_deleted", f"Run {int(run['id'])}", _details(conn, run))
    conn.execute("DELETE FROM runs WHERE id = ?", (run["id"],))
    logger.info("Run %s: deleted by %s.", run["id"], "an admin" if user.is_admin else "its owner")


def draft_days(value) -> int:
    """The age in whole days, or ValueError with one plain sentence."""
    if type(value) is not int or not 1 <= value <= MAX_DRAFT_DAYS:
        raise ValueError(f"Give the age as a whole number of days from 1 to {MAX_DRAFT_DAYS}.")
    return value


def abandoned_drafts(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    """Runs still at setup that nobody has touched for `days` days or more, with no work queued."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return conn.execute(
        "SELECT * FROM runs r WHERE r.status = ? AND r.updated_at <= ? AND NOT EXISTS (SELECT 1 FROM jobs j "
        "WHERE j.run_id = r.id AND j.status IN ('queued', 'working', 'retry')) ORDER BY r.id",
        (run_status.SETUP, cutoff)).fetchall()


def clear_drafts(conn: sqlite3.Connection, days: int, admin: User) -> list[int]:
    """Delete every abandoned draft and write one audit row naming them. Use
    inside `db.connect(immediate=True)`, then remove each run's files. Returns the run numbers."""
    drafts = abandoned_drafts(conn, days)
    run_ids = [int(r["id"]) for r in drafts]
    if run_ids:
        auth_store.add_audit(conn, admin.email, "drafts_cleared", f"{len(run_ids)} runs",
                             {"older_than_days": days, "runs": [_details(conn, r) for r in drafts]})
        conn.executemany("DELETE FROM runs WHERE id = ?", [(i,) for i in run_ids])
    logger.info("Abandoned drafts: an admin cleared %d run(s) at setup untouched for %d days or more.",
                len(run_ids), days)
    return run_ids

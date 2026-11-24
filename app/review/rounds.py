"""Correction rounds: send a person's open comments as one round, stop it,
and bring every round to a final state.

A round moves sent -> working -> done, failed or stopped. Sending is one
transaction: the round, its comments and its job together or not at all,
and the database allows one waiting or working round per run. However a
round ends (finished, failed, stopped, the step or time limit, a server
restart) the run goes back to `in_review`, and comments the Reviewer did not
answer go back to open. Answers and figure changes made so far are kept.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Optional

from app import db
from app.checks.runner import read_checks
from app.jobs import queue
from app.runs import status as run_status
from app.runs.events import add_event

logger = logging.getLogger(__name__)

JOB = "review_round"
SOURCE = "review"
ACTIVE = ("sent", "working")
FINAL = ("done", "failed", "stopped")
ALREADY_RUNNING = "A correction round is already running."
# The fill reads the figures as they stand when it starts, so a round now would make its file out of date.
FILLING = "The mTool file is being prepared, so send the comments when it is ready."
RESTARTED = "The server stopped while this round was working; the answers and changes so far are kept."


class RoundRefused(ValueError):
    def __init__(self, sentence: str, status: int = 409) -> None:
        super().__init__(sentence)
        self.status = status


def public(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """`Round` (docs/api-contract.md, Step 5a)."""
    ids = [r[0] for r in conn.execute("SELECT comment_id FROM round_comments WHERE round_id = ? ORDER BY comment_id",
                                      (row["id"],))]
    return {"id": row["id"], "run_id": row["run_id"], "number": row["number"], "status": row["status"],
            "sent_by": row["sent_by"], "sent_at": row["sent_at"], "started_at": row["started_at"],
            "finished_at": row["finished_at"], "summary": row["summary"], "error": row["error"],
            "stop_requested": bool(row["stop_requested"]), "comment_ids": ids}


def get_row(conn: sqlite3.Connection, run_id: int, round_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM rounds WHERE run_id = ? AND id = ?", (run_id, round_id)).fetchone()
    if row is None:
        raise RoundRefused("There is no such round in this run.", 404)
    return row


def list_rounds(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [public(conn, r) for r in conn.execute("SELECT * FROM rounds WHERE run_id = ? ORDER BY id", (run_id,))]


def active(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM rounds WHERE run_id = ? AND status IN ('sent', 'working')",
                        (run_id,)).fetchone()


def send(conn: sqlite3.Connection, run: sqlite3.Row, email: str, client_id: Any = None) -> sqlite3.Row:
    """Send every open comment a person wrote as one round. Use inside
    `db.connect(immediate=True)`. Raises RoundRefused."""
    run_id = run["id"]
    if client_id is not None:
        if not isinstance(client_id, str) or not 0 < len(client_id) <= 100:
            raise RoundRefused("The client id is up to 100 characters of text.", 422)
        earlier = conn.execute("SELECT * FROM rounds WHERE run_id = ? AND client_id = ?",
                               (run_id, client_id)).fetchone()
        if earlier is not None:
            return earlier
    if active(conn, run_id) is not None or run["status"] == run_status.CORRECTING:
        raise RoundRefused(ALREADY_RUNNING)
    if run["status"] == run_status.NEEDS_ANSWER:
        raise RoundRefused("Extraction is waiting for your answer to its question, so send the comments after it "
                           "finishes.")
    if run["status"] in (run_status.READY, run_status.EXTRACTING):
        raise RoundRefused("Extraction is still running, so send the comments when it finishes.")
    if run["status"] != run_status.IN_REVIEW:
        raise RoundRefused("Comments can be sent once extraction has finished.")
    if conn.execute("SELECT 1 FROM fills WHERE run_id = ? AND job_status IN ('queued', 'filling')",
                    (run_id,)).fetchone():
        raise RoundRefused(FILLING)
    ids = [r[0] for r in conn.execute("SELECT id FROM comments WHERE run_id = ? AND author_kind = 'person' "
                                      "AND status = 'open' ORDER BY id", (run_id,))]
    if not ids:
        raise RoundRefused("There are no open comments to send.", 422)
    number = conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM rounds WHERE run_id = ?", (run_id,)).fetchone()[0]
    stamp = db.now()
    try:
        round_id = int(conn.execute(
            "INSERT INTO rounds(run_id, number, status, sent_by, client_id, checks_before_json, sent_at) "
            "VALUES (?, ?, 'sent', ?, ?, ?, ?)",
            (run_id, number, email, client_id, json.dumps(read_checks(conn, run_id), default=str), stamp)).lastrowid)
    except sqlite3.IntegrityError as exc:   # the one-active-round index: a second Send raced this one
        raise RoundRefused(ALREADY_RUNNING) from exc
    conn.executemany("INSERT INTO round_comments(round_id, comment_id) VALUES (?, ?)", [(round_id, c) for c in ids])
    conn.execute(f"UPDATE comments SET status = 'sent', round_id = ?, updated_at = ? "
                 f"WHERE id IN ({','.join('?' * len(ids))})", [round_id, stamp, *ids])
    job_id = queue.enqueue_in(conn, JOB, {"round_id": round_id}, max_attempts=1, run_id=run_id)
    conn.execute("UPDATE rounds SET job_id = ? WHERE id = ?", (job_id, round_id))
    run_status.round_started(conn, run_id)
    conn.execute("INSERT INTO events(run_id, job_id, source, kind, message, data_json, created_at) "
                 "VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                 (run_id, job_id, SOURCE, f"Correction round {number} is queued: {len(ids)} comment(s).",
                  json.dumps({"round_id": round_id, "comments": len(ids)}), stamp))
    logger.info("Run %s: correction round %s (id %s) is queued with %s comment(s).", run_id, number, round_id,
                len(ids))
    return conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()


def _close(conn: sqlite3.Connection, row: sqlite3.Row, status: str, *, summary: Optional[str] = None,
           error: Optional[str] = None) -> None:
    """Bring one round to its final state, in the caller's transaction."""
    stamp = db.now()
    conn.execute("UPDATE rounds SET status = ?, summary = COALESCE(?, summary), error = ?, finished_at = ? "
                 "WHERE id = ?", (status, summary, error, stamp, row["id"]))
    conn.execute("UPDATE comments SET status = 'open', updated_at = ? WHERE status = 'sent' AND id IN "
                 "(SELECT comment_id FROM round_comments WHERE round_id = ?)", (stamp, row["id"]))
    current = conn.execute("SELECT status FROM runs WHERE id = ?", (row["run_id"],)).fetchone()
    if current is not None and current["status"] == run_status.CORRECTING:
        run_status.round_ended(conn, row["run_id"])


def stop(conn: sqlite3.Connection, run_id: int, round_id: int) -> sqlite3.Row:
    """Ask the Reviewer to stop before its next step; a waiting round stops at once."""
    row = get_row(conn, run_id, round_id)
    if row["status"] in FINAL:
        raise RoundRefused("This round has already ended.")
    conn.execute("UPDATE rounds SET stop_requested = 1 WHERE id = ?", (round_id,))
    if row["status"] == "sent":
        _close(conn, row, "stopped", error="Stopped on request before it started.")
        logger.info("Run %s: correction round %s was stopped before it started.", run_id, row["number"])
    return conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()


def begin(round_id: int) -> Optional[sqlite3.Row]:
    """Mark a waiting round working. None when it is not waiting (stopped already, say)."""
    with db.connect(immediate=True) as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
        if row is None or row["status"] != "sent":
            return None
        conn.execute("UPDATE rounds SET status = 'working', started_at = ? WHERE id = ?", (db.now(), round_id))
        return conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()


def end(round_id: int, status: str, *, summary: Optional[str] = None, error: Optional[str] = None,
        data: Optional[dict] = None, message: Optional[str] = None) -> None:
    """Bring a round to a final state, unless it reached one already, and write its event."""
    if status not in FINAL:
        raise ValueError(f"{status!r} is not a final round status.")
    with db.connect(immediate=True) as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
        if row is None or row["status"] in FINAL:
            return
        _close(conn, row, status, summary=summary, error=error)
    message = message or (f"Correction round {row['number']} is finished: {summary}" if status == "done" else
                          f"Correction round {row['number']} {'stopped' if status == 'stopped' else 'failed'}: "
                          f"{error}")
    try:
        add_event(SOURCE, status, message, run_id=row["run_id"], job_id=row["job_id"], data=data)
    except Exception:  # noqa: BLE001 - progress rows never end the work
        logger.warning("Could not record a review event", exc_info=True)


def stop_requested(round_id: int) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT stop_requested FROM rounds WHERE id = ?", (round_id,)).fetchone()
    return row is None or bool(row["stop_requested"])


def recover_after_restart() -> int:
    """A round left working by a previous process ends failed, and its job is
    not handed back: a second Reviewer would start from a half-done round. Run
    before the queue's own recovery."""
    with db.connect(immediate=True) as conn:
        rows = conn.execute("SELECT * FROM rounds WHERE status = 'working'").fetchall()
        for row in rows:
            _close(conn, row, "failed", error=RESTARTED)
            if row["job_id"] is not None:
                conn.execute("UPDATE jobs SET status = 'failed', last_error = ?, finished_at = ? "
                             "WHERE id = ? AND status IN ('working', 'retry', 'queued')",
                             (queue.RESTART_ERROR, db.now(), row["job_id"]))
            conn.execute("INSERT INTO events(run_id, job_id, source, kind, message, created_at) "
                         "VALUES (?, ?, ?, 'failed', ?, ?)",
                         (row["run_id"], row["job_id"], SOURCE,
                          f"Correction round {row['number']} failed: {RESTARTED}", db.now()))
            logger.warning("Run %s: correction round %s was working when the server stopped; it is marked failed.",
                           row["run_id"], row["number"])
    return len(rows)

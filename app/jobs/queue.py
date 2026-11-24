"""The job queue, stored in the `jobs` table.

A job moves queued -> working -> done. A failure moves it to `retry` (run
again later) while attempts remain, and to `failed` when they are used up.
Each claim counts one attempt. An attempt cut short by a server stop does not
count: start-up recovery hands it back for retry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from app import db

DEFAULT_MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0
RESTART_ERROR = "The server stopped while this job was working."


@dataclass
class Job:
    id: int
    kind: str
    payload: dict
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str]
    run_id: Optional[int]
    stage_id: Optional[int]


def _job(row) -> Job:
    return Job(
        id=row["id"], kind=row["kind"], payload=json.loads(row["payload_json"] or "{}"),
        status=row["status"], attempts=row["attempts"], max_attempts=row["max_attempts"],
        last_error=row["last_error"], run_id=row["run_id"], stage_id=row["stage_id"],
    )


def _later(seconds: float) -> str:
    when = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def enqueue(
    kind: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    run_id: Optional[int] = None,
    stage_id: Optional[int] = None,
) -> int:
    with db.connect() as conn:
        return enqueue_in(conn, kind, payload, max_attempts=max_attempts, run_id=run_id, stage_id=stage_id)


def enqueue_in(
    conn,
    kind: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    run_id: Optional[int] = None,
    stage_id: Optional[int] = None,
) -> int:
    """`enqueue` inside the caller's transaction, so the job and the rows it
    belongs to are saved together or not at all."""
    if max_attempts < 1:
        raise ValueError("A job needs at least one attempt.")
    stamp = db.now()
    cur = conn.execute(
        "INSERT INTO jobs(kind, payload_json, max_attempts, run_after, run_id, stage_id, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, json.dumps(payload or {}), max_attempts, stamp, run_id, stage_id, stamp),
    )
    return int(cur.lastrowid)


def get(job_id: int) -> Optional[Job]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job(row) if row else None


def claim(busy_kinds: Iterable[str] = ()) -> Optional[Job]:
    """Take the oldest job that is due and mark it working. `busy_kinds` are
    the kinds already working in this worker: a job of one of them waits, so
    two jobs running at once are always of different stages."""
    stamp = db.now()
    busy = sorted(set(busy_kinds))
    skip = f" AND kind NOT IN ({', '.join('?' * len(busy))})" if busy else ""
    with db.connect(immediate=True) as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'retry') AND run_after <= ?" + skip
            + " ORDER BY run_after, id LIMIT 1",
            (stamp, *busy),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'working', attempts = attempts + 1, started_at = ? "
            "WHERE id = ?",
            (stamp, row["id"]),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
    return _job(row)


def complete(job_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', last_error = NULL, finished_at = ? WHERE id = ?",
            (db.now(), job_id),
        )


def _fail(conn, row, error: str, retry_delay: float) -> str:
    status = "retry" if row["attempts"] < row["max_attempts"] else "failed"
    conn.execute(
        "UPDATE jobs SET status = ?, last_error = ?, run_after = ?, finished_at = ? WHERE id = ?",
        (status, error, _later(retry_delay) if status == "retry" else row["run_after"],
         db.now() if status == "failed" else None, row["id"]),
    )
    return status


def fail(job_id: int, error: str, *, retry_delay: float = RETRY_DELAY_SECONDS) -> str:
    """Record a failed attempt. Returns the new status: `retry` or `failed`."""
    with db.connect(immediate=True) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise LookupError(f"No job {job_id}.")
        return _fail(conn, row, error, retry_delay)


def recover_after_restart() -> int:
    """Put every job left `working` by a previous process back for retry. The
    interrupted attempt is not a failed one, so it is not counted against the
    job. Returns how many were found."""
    with db.connect(immediate=True) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'retry', attempts = MAX(attempts - 1, 0), last_error = ?, "
            "run_after = ?, finished_at = NULL WHERE status = 'working'",
            (RESTART_ERROR, db.now()),
        )
    return cur.rowcount

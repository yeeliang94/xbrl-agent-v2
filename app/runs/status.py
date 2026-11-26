"""The one place a run's status changes.

A run moves: reading -> setup (the map is saved) -> ready (setup confirmed)
-> extracting (the figures agent works) -> in_review (extraction finished)
or needs_answer (the agent asked a scope question; the answer sends it back
to ready, and extraction starts again). A person may stop extraction: the
run goes to in_review with the figures saved so far, or to stopped when
there are none; a retry sends either back to ready.
From step 6 the notes agent works beside the figures agent in its own
`notes` stage. While a run has a notes stage, its status is worked out from
both stages together (`settle`): extracting while either works, needs_answer
while either asks, and in review (or failed, when extraction failed) only
once both have finished, failed or stopped. From step 10 the reports agent's
`reports` stage counts the same way, except that its failure never fails
the run.
-> correcting (a correction round works) -> in_review (the round ended, in
any way). Reading or extraction can fail (failed); a retry of reading sends
it back to reading, a retry of extraction back to ready. A person may stop
reading too (stopped, with the read stage stopped); a retry reads on from
the pages already read. Every other module
calls a named function here instead of writing `runs.status` itself, so the
transitions can be read in one file.
"""
from __future__ import annotations

import sqlite3

from app.db import now

READING, SETUP, READY, FAILED = "reading", "setup", "ready", "failed"
EXTRACTING, IN_REVIEW, CORRECTING = "extracting", "in_review", "correcting"
NEEDS_ANSWER, STOPPED = "needs_answer", "stopped"


def _set(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    conn.execute("UPDATE runs SET status = ?, updated_at = ? WHERE id = ?", (status, now(), run_id))


def reading_started(conn: sqlite3.Connection, run_id: int) -> None:
    """Reading is queued or working (also on a retry)."""
    _set(conn, run_id, READING)


def reading_done(conn: sqlite3.Connection, run_id: int) -> None:
    """The document map is saved: the run waits for a person at setup."""
    _set(conn, run_id, SETUP)


def reading_failed(conn: sqlite3.Connection, run_id: int) -> None:
    _set(conn, run_id, FAILED)


def reading_stopped(conn: sqlite3.Connection, run_id: int) -> None:
    """A person stopped the reading: the pages read are kept and reading can be tried again."""
    _set(conn, run_id, STOPPED)


def setup_confirmed(conn: sqlite3.Connection, run_id: int) -> None:
    """The person confirmed the setup: the run waits for extraction."""
    _set(conn, run_id, READY)


def extraction_started(conn: sqlite3.Connection, run_id: int) -> None:
    _set(conn, run_id, EXTRACTING)


def _has_notes_stage(conn: sqlite3.Connection, run_id: int) -> bool:
    """True when another agent stage works beside extraction: the notes agent, or (step 10) the reports agent."""
    return conn.execute("SELECT 1 FROM stages WHERE run_id = ? AND name IN ('notes', 'reports')",
                        (run_id,)).fetchone() is not None


def has_notes(conn: sqlite3.Connection, run_id: int) -> bool:
    return conn.execute("SELECT 1 FROM notes WHERE run_id = ? LIMIT 1", (run_id,)).fetchone() is not None


def settle(conn: sqlite3.Connection, run_id: int) -> None:
    """The run's status from its extract, notes and reports stages, after one of them changed. Call it after
    the stage row is written."""
    stages = {r["name"]: r["status"] for r in conn.execute(
        "SELECT name, status FROM stages WHERE run_id = ? AND name IN ('extract', 'notes', 'reports')", (run_id,))}
    states = set(stages.values())
    current = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if "asking" in states:
        _set(conn, run_id, NEEDS_ANSWER)
    elif "working" in states or ("waiting" in states and (current is None or current["status"] != READY)):
        _set(conn, run_id, EXTRACTING)
    elif "waiting" in states:
        return   # still ready: nothing has started yet
    elif stages.get("extract") == "failed" or (stages.get("notes") == "failed" and "extract" not in stages):
        _set(conn, run_id, FAILED)
    elif "stopped" in states and not (has_figures(conn, run_id) or has_notes(conn, run_id)):
        _set(conn, run_id, STOPPED)
    else:
        _set(conn, run_id, IN_REVIEW)


def extraction_done(conn: sqlite3.Connection, run_id: int) -> None:
    """The figures are saved: the run waits for a person's review (once the notes stage has ended too)."""
    if _has_notes_stage(conn, run_id):
        return settle(conn, run_id)
    _set(conn, run_id, IN_REVIEW)


def extraction_failed(conn: sqlite3.Connection, run_id: int) -> None:
    if _has_notes_stage(conn, run_id):
        return settle(conn, run_id)
    _set(conn, run_id, FAILED)


def extraction_retried(conn: sqlite3.Connection, run_id: int) -> None:
    """A failed extraction is queued again: the run waits for it, as after setup."""
    _set(conn, run_id, READY)


def extraction_asked(conn: sqlite3.Connection, run_id: int) -> None:
    """The figures agent stopped to ask a scope question: the run waits for a person's answer."""
    _set(conn, run_id, NEEDS_ANSWER)


def extraction_stopped(conn: sqlite3.Connection, run_id: int, has_figures: bool) -> None:
    """A person stopped extraction: in review with the figures saved so far, or stopped when there are none.
    Either can be retried."""
    if _has_notes_stage(conn, run_id):
        return settle(conn, run_id)
    _set(conn, run_id, IN_REVIEW if has_figures else STOPPED)


def notes_started(conn: sqlite3.Connection, run_id: int) -> None:
    """The notes agent works: the run is extracting."""
    _set(conn, run_id, EXTRACTING)


def notes_ended(conn: sqlite3.Connection, run_id: int) -> None:
    """The notes stage finished, failed, stopped or asked: the run follows both stages."""
    settle(conn, run_id)


def has_figures(conn: sqlite3.Connection, run_id: int) -> bool:
    return conn.execute("SELECT 1 FROM figures WHERE run_id = ? AND ((value IS NOT NULL AND status != 'not_disclosed') "
                        "OR stated_value IS NOT NULL) LIMIT 1", (run_id,)).fetchone() is not None


def question_answered(conn: sqlite3.Connection, run_id: int) -> None:
    """A person answered: extraction is queued again, so the run waits for it, as after setup."""
    _set(conn, run_id, READY)


def round_started(conn: sqlite3.Connection, run_id: int) -> None:
    """A person sent comments: a correction round is queued or working."""
    _set(conn, run_id, CORRECTING)


def round_ended(conn: sqlite3.Connection, run_id: int) -> None:
    """The round is done, failed or stopped: the run is back in review."""
    _set(conn, run_id, IN_REVIEW)

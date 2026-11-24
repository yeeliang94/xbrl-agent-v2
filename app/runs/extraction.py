"""Where extraction starts once a person confirms a run's setup.

`confirm_setup` calls `start_extraction`, `start_notes` and (step 10) `start_reports` inside the same
transaction that saved the setup, so a run is never left confirmed with its
agents half-queued. The jobs are `app/extraction/job.py` (the figures agent,
stage `extract`) and `app/notes/job.py` (the notes agent, stage `notes`).
Stop stops both agents; retry queues again whichever of them failed or was
stopped. Each keeps what it saved.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from app.db import now


def start_extraction(conn: sqlite3.Connection, run_id: int) -> Optional[int]:
    """Queue the extraction of a confirmed run. Returns the job id, or None
    when the setup includes no statement."""
    from app.extraction import job

    return job.start(conn, run_id)


def start_notes(conn: sqlite3.Connection, run_id: int) -> Optional[int]:
    """Queue the notes agent of a confirmed run. Returns the job id, or None when the notes are switched off."""
    from app.notes import job

    return job.start(conn, run_id)


def start_reports(conn: sqlite3.Connection, run_id: int) -> Optional[int]:
    """Queue the reports agent of a confirmed run (step 10). Returns the job id, or None when the Reader found
    no report section."""
    from app.reports import job

    return job.start(conn, run_id)


class NothingToStop(ValueError):
    def __init__(self) -> None:
        super().__init__("Extraction is not running, so there is nothing to stop.")


def _stop_waiting_job(conn: sqlite3.Connection, run_id: int, stage: str, kind: str, sentence: str,
                      source: str, message: str) -> bool:
    """Stop a stage whose job has not started yet. False when the worker has just taken it."""
    waiting = conn.execute("UPDATE jobs SET status = 'done', last_error = 'Stopped before it started.', "
                           "finished_at = ? WHERE run_id = ? AND kind = ? AND status IN ('queued', 'retry')",
                           (now(), run_id, kind)).rowcount
    if not waiting:
        return False   # the worker has just taken it: it sees the request when it starts
    conn.execute("UPDATE stages SET status = 'stopped', finished_at = ?, error = ?, working_on = NULL "
                 "WHERE run_id = ? AND name = ?", (now(), sentence, run_id, stage))
    conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, 'stopped', ?, ?)",
                 (run_id, source, message, now()))
    return True


def stop_extraction(conn: sqlite3.Connection, run_id: int) -> bool:
    """Ask the run's agents (figures and notes) to stop. Use inside
    `db.connect(immediate=True)`. A job still waiting to start is stopped at
    once; a working one stops before the agent's next step, keeping every
    figure and note saved. Returns True when every agent stopped at once.
    Raises NothingToStop."""
    from app.extraction import job
    from app.notes import job as notes_job
    from app.reports import job as reports_job
    from app.runs import status

    run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    stages = {r["name"]: r["status"] for r in conn.execute(
        "SELECT name, status FROM stages WHERE run_id = ? AND name IN ('extract', 'notes', 'reports')", (run_id,))}
    running = [name for name in ("extract", "notes", "reports") if stages.get(name) in ("waiting", "working")]
    if run is None or run["status"] not in (status.READY, status.EXTRACTING) or not running:
        raise NothingToStop()
    stopped_now = []
    for name in running:
        conn.execute("UPDATE stages SET stop_requested = 1 WHERE run_id = ? AND name = ?", (run_id, name))
        if stages[name] == "working":
            continue
        if name == "extract":
            done = _stop_waiting_job(conn, run_id, "extract", job.EXTRACT_JOB, job.STOPPED_SENTENCE, job.SOURCE,
                                     "Extraction stopped on request before it started.")
        elif name == "notes":
            done = _stop_waiting_job(conn, run_id, "notes", notes_job.NOTES_JOB, notes_job.STOPPED_SENTENCE,
                                     notes_job.SOURCE, "The notes agent stopped on request before it started.")
        else:
            done = _stop_waiting_job(conn, run_id, "reports", reports_job.REPORTS_JOB, reports_job.STOPPED_SENTENCE,
                                     reports_job.SOURCE, "The reports agent stopped on request before it started.")
        if done:
            stopped_now.append(name)
    if stopped_now:
        status.extraction_stopped(conn, run_id, status.has_figures(conn, run_id))
    return len(stopped_now) == len(running)


class NothingToRetry(ValueError):
    def __init__(self) -> None:
        super().__init__("Extraction has not failed, so there is nothing to try again.")


def retry_extraction(conn: sqlite3.Connection, run_id: int) -> Optional[int]:
    """Queue again whichever agent failed or was stopped: extraction in the
    same `extract` stage row, the notes agent in its `notes` row. Use inside
    `db.connect(immediate=True)`. Nothing is cleared: figures and notes
    already saved, a person's edits among them, are kept and the agents start
    from them. Returns the extract job id, or the notes job id when only the
    notes agent is queued. Raises NothingToRetry unless one of them failed, or
    a person stopped it (step 5c) and no correction round is running."""
    from app.extraction import job
    from app.notes import job as notes_job
    from app.reports import job as reports_job
    from app.runs import status

    run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    stages = {r["name"]: r["status"] for r in conn.execute(
        "SELECT name, status FROM stages WHERE run_id = ? AND name IN ('extract', 'notes', 'reports')", (run_id,))}
    settled = run is not None and run["status"] in (status.FAILED, status.STOPPED, status.IN_REVIEW)
    extract = stages.get("extract")
    extract_again = run is not None and ((run["status"] == status.FAILED and extract == "failed")
                                         or (run["status"] in (status.STOPPED, status.IN_REVIEW)
                                             and extract == "stopped"))
    notes_again = settled and stages.get("notes") in ("failed", "stopped")
    job_id = job.start(conn, run_id) if extract_again else None
    notes_id = notes_job.start(conn, run_id) if notes_again else None
    reports_again = settled and stages.get("reports") in ("failed", "stopped")
    reports_id = reports_job.start(conn, run_id) if reports_again else None
    if job_id is None and notes_id is None and reports_id is None:
        raise NothingToRetry()
    status.extraction_retried(conn, run_id)
    return next(i for i in (job_id, notes_id, reports_id) if i is not None)

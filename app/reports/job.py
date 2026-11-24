"""The `reports` job: the reports agent fills the three reports' fields, in
its own `reports` stage. Confirming the setup queues it (`app/runs/setup.py`
through `app/runs/extraction.start_reports`) when the Reader found any
report section; otherwise an event says why it does not run. There is no
setup switch: the screens for it wait on an owner-approved prototype.

The worker runs it beside, or after, the figures and notes agents. While it
waits or works the run is extracting; the run is ready for review once every
agent stage has ended (`app/runs/status.settle`). A failed reports stage
never fails the run: its error is its one plain sentence.

The stage is done when the agent finished, also at a step or time limit (an
event says it is partly done and how many fields are left). It fails, with
one plain sentence, when the model failed, or when it saved nothing while
fields are still unassessed (a retry that finds every field already assessed
and saves nothing new is done); every field already saved is kept. A person may stop it with the run's Stop:
it ends `stopped`, keeping its fields. A server restart hands the job back
once and the agent starts again from the fields already saved.

Everything is findable by run id: the stage, the events (source
`reports`), the model calls, the transcript and a record in
`runs/run-<id>/reports.json`, all in the traces.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app import db
from app.agents import loop
from app.jobs import queue
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.models import usage as model_usage
from app.reports import agent, store
from app.runs import status as run_status
from app.runs.events import add_event
from app.settings import store as settings
from app.utils.atomic_io import write_json_atomic
from app.utils.paths import output_dir

logger = logging.getLogger(__name__)

REPORTS_JOB = "reports"
STAGE = "reports"
SOURCE = "reports"
STOPPED_SENTENCE = "Stopped on request; the report fields saved so far are kept."
NO_SECTION = "The Reader found no directors' report, statement by directors or auditors' report, so the reports " \
             "agent does not run."


class ReportsFailed(RuntimeError):
    """The stage failed; `str()` is the plain sentence already recorded."""


def _event(run_id: int, job_id: Optional[int], kind: str, message: str, data: Optional[dict] = None) -> None:
    try:
        add_event(SOURCE, kind, message, run_id=run_id, job_id=job_id, data=data)
    except Exception:  # noqa: BLE001 - progress rows never end the work
        logger.warning("Could not record a reports event", exc_info=True)


def start(conn, run_id: int) -> Optional[int]:
    """Queue the reports agent in the caller's transaction. Returns the job id, or None when the Reader found
    no report section."""
    if not agent.report_sections(conn, run_id):
        conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, 'notice', ?, ?)",
                     (run_id, SOURCE, NO_SECTION, db.now()))
        return None
    row = conn.execute("SELECT id FROM stages WHERE run_id = ? AND name = ?", (run_id, STAGE)).fetchone()
    if row is None:
        stage_id = int(conn.execute("INSERT INTO stages(run_id, name, status) VALUES (?, ?, 'waiting')",
                                    (run_id, STAGE)).lastrowid)
    else:
        stage_id = int(row["id"])
        conn.execute("UPDATE stages SET status = 'waiting', started_at = NULL, finished_at = NULL, error = NULL, "
                     "working_on = NULL, stop_requested = 0 WHERE id = ?", (stage_id,))
    conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, 'queued', ?, ?)",
                 (run_id, SOURCE, "The reports agent is queued.", db.now()))
    return queue.enqueue_in(conn, REPORTS_JOB, {}, max_attempts=1, run_id=run_id, stage_id=stage_id)


def stage_status(conn, run_id: int) -> Optional[str]:
    row = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = ?", (run_id, STAGE)).fetchone()
    return row["status"] if row else None


def stop_requested(run_id: int) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT stop_requested FROM stages WHERE run_id = ? AND name = ?",
                           (run_id, STAGE)).fetchone()
    return bool(row and row["stop_requested"])


def _stage(run_id: int, status: str, error: Optional[str] = None) -> None:
    stamp = db.now()
    with db.connect(immediate=True) as conn:
        if status == "working":
            conn.execute("UPDATE stages SET status = 'working', started_at = ?, finished_at = NULL, error = NULL "
                         "WHERE run_id = ? AND name = ?", (stamp, run_id, STAGE))
        else:
            conn.execute("UPDATE stages SET status = ?, finished_at = ?, error = ?, working_on = NULL "
                         "WHERE run_id = ? AND name = ?", (status, stamp, error, run_id, STAGE))
        run_status.settle(conn, run_id)


def _fail(run_id: int, job_id: Optional[int], sentence: str) -> ReportsFailed:
    _stage(run_id, "failed", sentence)
    _event(run_id, job_id, "failed", f"The reports agent stopped: {sentence}", model_usage.run_totals(run_id, SOURCE))
    logger.warning("Run %s: the reports stage failed: %s", run_id, sentence)
    return ReportsFailed(sentence)


def _write_record(run_id: int, record: dict) -> None:
    try:
        write_json_atomic(output_dir() / "runs" / f"run-{int(run_id)}" / "reports.json", record)
    except Exception:  # noqa: BLE001 - the stage's own result comes first
        logger.warning("Run %s: could not write the reports record.", run_id, exc_info=True)


def _left(run_id: int) -> int:
    with db.connect() as conn:
        return len(store.not_assessed(conn, run_id))


async def run_reports(run_id: int, job_id: Optional[int] = None, *, model: Any = None,
                      max_steps: Optional[int] = None) -> None:
    """Run the reports stage. Raises ReportsFailed when it fails. `model` replaces the factory's, for tests."""
    if stop_requested(run_id):
        _stage(run_id, "stopped", STOPPED_SENTENCE)
        _event(run_id, job_id, "stopped", "The reports agent stopped on request before it started.")
        return
    logger.info("Run %s: the reports stage starts.", run_id)
    started = time.monotonic()
    try:
        _stage(run_id, "working")
        model_id = settings.read()["models"]["extraction"]
        logger.info("Run %s: the reports agent starts with %s.", run_id, model_id)
        outcome, deps = await agent.run(run_id, model_id, job_id=job_id, model=model,
                                        should_stop=lambda: stop_requested(run_id), max_steps=max_steps)
    except agent.CannotStart as exc:
        raise _fail(run_id, job_id, str(exc)) from exc
    except Exception as exc:
        logger.exception("Run %s: the reports stage hit an unexpected error.", run_id)
        raise _fail(run_id, job_id, "The reports agent stopped on an unexpected error.") from exc
    seconds = time.monotonic() - started
    left = _left(run_id)
    record = {"run_id": run_id, **agent.record(outcome, deps), "seconds": round(seconds), "not_assessed": left,
              "usage": model_usage.run_totals(run_id, SOURCE)}
    _write_record(run_id, record)
    logger.info("Run %s: the reports agent ended %s after %s steps in %.0f s, %s write(s), %s field(s) left.",
                run_id, outcome.status, outcome.steps, seconds, deps.writes, left)
    if outcome.error:
        logger.warning("Run %s: the reports agent's error: %s", run_id, outcome.error)
    if outcome.status == loop.STOPPED and stop_requested(run_id):
        _stage(run_id, "stopped", STOPPED_SENTENCE)
        _event(run_id, job_id, "stopped", "The reports agent stopped on request. The fields saved so far are kept.")
        return
    if outcome.status in (loop.FAILED, loop.STOPPED):
        raise _fail(run_id, job_id, f"{outcome.message.rstrip('.')}; the report fields saved so far are kept.")
    if deps.writes == 0 and left:
        raise _fail(run_id, job_id, "No report field was saved.")
    _stage(run_id, "done")
    open_points = len((deps.finish or {}).get("unresolved") or [])
    if outcome.status == loop.COMPLETED:
        message = "The reports are filled" + (f", {left} field(s) not assessed" if left else "") + \
                  (f", {open_points} point(s) for a person." if open_points else ".")
    else:
        message = f"The reports are partly filled, {left} field(s) not assessed. {outcome.message}"
    _event(run_id, job_id, "done", message, {"status": outcome.status, "not_assessed": left,
                                             "unresolved": open_points, **record["usage"]})


@handler(REPORTS_JOB)
async def reports_job(job: Job) -> None:
    await run_reports(int(job.run_id), job.id)

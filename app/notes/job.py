"""The `notes` job: the notes agent places the run's notes, in its own
`notes` stage beside the figures agent's `extract` stage. Confirming the
setup queues both (`app/runs/extraction.py`) unless the person switched the
notes off at setup. The worker runs the two side by side
(`app/jobs/worker.py`). The run is ready for review once both stages have
finished, failed or stopped (`app/runs/status.settle`).

The agent runs in sessions side by side (`agent.SESSIONS`), each its own
agent with its own transcript. The placing session places every note while
the numeric session saves the share capital and related-party figures; once
placing ends, formatting sessions set the look of their own groups of notes
(`briefing.look_groups`) beside the numeric session. Only the placing session
places, so sessions never race over a placement; each write is one short
SQLite transaction. A session that reaches its step or time limit leaves its
work kept. Code checks coverage by source blocks once every session ended.

The stage fails, with one plain sentence, when a session's model fails, or
when nothing at all was placed or reported; every note already placed is
kept, and the server log keeps the full error. A failed session never stops
the others mid-write: they run on to their own end. A person may stop the
stage (the run's Stop stops every session between steps): it ends `stopped`
keeping the notes. A server restart hands the job back once, and every
session starts from the notes already placed.

A scope question from either agent stops both stages, keeping their work:
the stage is `asking` and the run `needs_answer` until a person answers;
the answer queues this job again (`after_answer`). Any question asked or
answered while the sessions work stops every session between steps; when
the answer is already in by the time the last session ends, the stage starts
again at once in the same job, every session with fresh deps (the answer may
have changed the setup).

Everything is findable by run id: the stage, events, the model calls, the
transcripts, the preview pictures (`runs/run-<id>/note-previews/`) and a
record of each session in `runs/run-<id>/notes.json`, all in the traces.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app import db
from app.agents import loop
from app.jobs import queue
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.models import usage as model_usage
from app.notes import agent, briefing, coverage
from app.notes.instructions import SESSIONS as SESSION_TEXT
from app.runs import status as run_status
from app.runs.events import add_event
from app.settings import store as settings
from app.utils.atomic_io import write_json_atomic
from app.utils.paths import output_dir

logger = logging.getLogger(__name__)

NOTES_JOB = "notes"
STAGE = "notes"
SOURCE = "notes"
STOPPED_SENTENCE = "Stopped on request; the notes placed so far are kept."
SWITCHED_OFF = "The notes are switched off at setup, so the notes agent does not run."


class NotesFailed(RuntimeError):
    """The stage failed; `str()` is the plain sentence already recorded."""


def _event(run_id: int, job_id: Optional[int], kind: str, message: str, data: Optional[dict] = None) -> None:
    try:
        add_event(SOURCE, kind, message, run_id=run_id, job_id=job_id, data=data)
    except Exception:  # noqa: BLE001 - progress rows never end the work
        logger.warning("Could not record a notes event", exc_info=True)


def start(conn, run_id: int) -> Optional[int]:
    """Queue the notes agent in the caller's transaction. Returns the job id, or None when the notes are
    switched off at setup."""
    setup = conn.execute("SELECT notes_included FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
    if setup is not None and not setup["notes_included"]:
        conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, 'notice', ?, ?)",
                     (run_id, SOURCE, SWITCHED_OFF, db.now()))
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
                 (run_id, SOURCE, "The notes agent is queued.", db.now()))
    return queue.enqueue_in(conn, NOTES_JOB, {}, max_attempts=1, run_id=run_id, stage_id=stage_id)


def stage_status(conn, run_id: int) -> Optional[str]:
    row = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = ?", (run_id, STAGE)).fetchone()
    return row["status"] if row else None


def after_answer(conn, run_id: int) -> Optional[int]:
    """A person answered the run's scope question: a notes stage that stopped to wait starts again, from the
    notes already placed. A job still queued (handed back after a restart) takes the answer. Use inside the
    answer's transaction."""
    if stage_status(conn, run_id) != "asking":
        return None
    waiting = conn.execute("SELECT id FROM jobs WHERE run_id = ? AND kind = ? AND status IN ('queued', 'retry')",
                           (run_id, NOTES_JOB)).fetchone()
    if waiting is not None:
        conn.execute("UPDATE stages SET status = 'waiting', started_at = NULL, finished_at = NULL, error = NULL "
                     "WHERE run_id = ? AND name = ?", (run_id, STAGE))
        return int(waiting["id"])
    return start(conn, run_id)


def stop_requested(run_id: int) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT stop_requested FROM stages WHERE run_id = ? AND name = ?",
                           (run_id, STAGE)).fetchone()
    return bool(row and row["stop_requested"])


def _waiting(run_id: int) -> bool:
    """True when the run has an open scope question: the stage waits for the answer, keeping its notes."""
    with db.connect(immediate=True) as conn:
        if conn.execute("SELECT 1 FROM scope_questions WHERE run_id = ? AND status = 'open'",
                        (run_id,)).fetchone() is None:
            return False
        conn.execute("UPDATE stages SET status = 'asking', error = NULL, working_on = NULL WHERE run_id = ? "
                     "AND name = ?", (run_id, STAGE))
        run_status.notes_ended(conn, run_id)
    return True


def _questions(run_id: int) -> tuple:
    """The run's scope questions and their states: a change means one was asked or answered."""
    with db.connect() as conn:
        return tuple(tuple(r) for r in conn.execute("SELECT id, status FROM scope_questions WHERE run_id = ? "
                                                     "ORDER BY id", (run_id,)))


def _stage(run_id: int, status: str, error: Optional[str] = None) -> None:
    stamp = db.now()
    with db.connect(immediate=True) as conn:
        if status == "working":
            conn.execute("UPDATE stages SET status = 'working', started_at = ?, finished_at = NULL, error = NULL "
                         "WHERE run_id = ? AND name = ?", (stamp, run_id, STAGE))
            run_status.notes_started(conn, run_id)
        else:
            conn.execute("UPDATE stages SET status = ?, finished_at = ?, error = ?, working_on = NULL "
                         "WHERE run_id = ? AND name = ?", (status, stamp, error, run_id, STAGE))
            run_status.notes_ended(conn, run_id)


def _fail(run_id: int, job_id: Optional[int], sentence: str) -> NotesFailed:
    _stage(run_id, "failed", sentence)
    _event(run_id, job_id, "failed", f"The notes agent stopped: {sentence}", model_usage.run_totals(run_id, "notes"))
    logger.warning("Run %s: the notes stage failed: %s", run_id, sentence)
    return NotesFailed(sentence)


def _stopped(run_id: int, job_id: Optional[int]) -> None:
    _stage(run_id, "stopped", STOPPED_SENTENCE)
    _event(run_id, job_id, "stopped", "The notes agent stopped on request. The notes placed so far are kept.")
    logger.info("Run %s: the notes stage was stopped on request.", run_id)


def _write_record(run_id: int, record: dict) -> None:
    try:
        write_json_atomic(output_dir() / "runs" / f"run-{int(run_id)}" / "notes.json", record)
    except Exception:  # noqa: BLE001 - the stage's own result comes first
        logger.warning("Run %s: could not write the notes record.", run_id, exc_info=True)


@dataclass
class _Sessions:
    """The sessions of one stage run: what runs now (the stage's working_on), and how each ended."""
    run_id: int
    job_id: Optional[int]
    model_id: str
    model: Any
    max_steps: Optional[int]
    record: dict
    previews: dict = field(default_factory=dict)
    running: list[str] = field(default_factory=list)
    ended: dict[str, str] = field(default_factory=dict)       # session name -> asked, stopped, failed or done
    failure: Optional[str] = None                             # the first failed session's sentence
    broken: bool = False                                      # an unexpected error: the others stop between steps
    questions: tuple = ()                                     # the scope questions when these sessions started

    def asked(self) -> bool:
        """A scope question was asked or answered since these sessions started."""
        return _questions(self.run_id) != self.questions

    def _working_on(self) -> None:
        with db.connect(immediate=True) as conn:
            conn.execute("UPDATE stages SET working_on = ? WHERE run_id = ? AND name = ?",
                         (", ".join(self.running) or None, self.run_id, STAGE))

    def should_stop(self) -> Any:
        if self.broken:
            return "Stopped because another session of the notes agent hit an unexpected error."
        if self.asked():
            return agent.ASKED_STOP
        return stop_requested(self.run_id)

    async def run(self, session: str, name: str, group: tuple[int, ...] = (), label: str = "") -> str:
        """Run one session to its end. Returns how it ended; raises only on an unexpected error. `label` names it
        on the activity rows (its title when not given), so sessions running side by side can be told apart."""
        started = time.monotonic()
        self.running.append(name)
        self._working_on()
        title = SESSION_TEXT[session][0]
        label = label or title
        _event(self.run_id, self.job_id, "session", f"Working on {title.lower()}"
               + (f" ({len(group)} note(s))." if group else "."),
               {"session": name, "agent": label, "notes": list(group)})
        logger.info("Run %s: the notes agent starts its %s session with %s.", self.run_id, name, self.model_id)
        try:
            outcome, deps = await agent.run_session(
                self.run_id, session, self.model_id, job_id=self.job_id, model=self.model, previews=self.previews,
                should_stop=self.should_stop, max_steps=self.max_steps, group=group, name=name, label=label)
        except BaseException:
            self.broken = True
            raise
        finally:
            self.running.remove(name)
            self._working_on()
        seconds = time.monotonic() - started
        self.record["sessions"].append({**agent.record(outcome, deps), "seconds": round(seconds)})
        _write_record(self.run_id, self.record)
        logger.info("Run %s: the notes %s session ended %s after %s steps in %.0f s, %s change(s).", self.run_id,
                    name, outcome.status, outcome.steps, seconds, deps.writes)
        if outcome.error:
            logger.warning("Run %s: the notes agent's %s error: %s", self.run_id, name, outcome.error)
        if deps.asked is not None or (outcome.status == loop.STOPPED and self.asked()):
            ended = "asked"
        elif outcome.status == loop.STOPPED and stop_requested(self.run_id):
            ended = "stopped"
        elif outcome.status in (loop.FAILED, loop.STOPPED):
            ended = "failed"
            self.failure = self.failure or f"{outcome.message.rstrip('.')}; the notes placed so far are kept."
        else:
            ended = "done"
            open_points = len((deps.finish or {}).get("unresolved") or [])
            finished = outcome.status == loop.COMPLETED
            _event(self.run_id, self.job_id, "finished" if finished else "notice",
                   (f"{title}: done" + (f", with {open_points} point(s) left open." if open_points else "."))
                   if finished else f"{title}: partly done. {outcome.message}",
                   {"session": name, "agent": label, "status": outcome.status, "steps": outcome.steps,
                    "seconds": round(seconds),
                    "unresolved": open_points})
        self.ended[name] = ended
        return ended

    async def formatting(self) -> None:
        with db.connect() as conn:
            groups = briefing.look_groups(conn, self.run_id)
        if not groups:
            _event(self.run_id, self.job_id, "notice", "No placed note holds a table, so no formatting session runs.")
            return
        title = SESSION_TEXT["look"][0]
        labels = [f"{title}, {k} of {len(groups)}" if len(groups) > 1 else title for k in range(1, len(groups) + 1)]
        await _together([self.run("look", f"look-{k}", tuple(g), labels[k - 1]) for k, g in enumerate(groups, 1)])


async def _together(runs: list) -> None:
    """Run sessions side by side and wait for every one; then raise the first unexpected error, if any."""
    results = await asyncio.gather(*runs, return_exceptions=True)
    error = next((r for r in results if isinstance(r, BaseException)), None)
    if error is not None:
        raise error


async def _sessions(run_id: int, job_id: Optional[int], model_id: str, model: Any, sessions: tuple[str, ...],
                    max_steps: Optional[int], record: dict) -> Optional[str]:
    """Placing, then formatting, with the numeric session beside both. Returns "asked" or "stopped" when the
    stage ends early, else None. Raises NotesFailed when a session failed, once every session has ended."""
    run = _Sessions(run_id, job_id, model_id, model, max_steps, record, questions=_questions(run_id))

    async def placing_then_formatting() -> None:
        if "placing" in sessions and await run.run("placing", "placing") != "done":
            return
        if "look" in sessions:
            await run.formatting()

    await _together([placing_then_formatting(), *([run.run("numeric", "numeric")] if "numeric" in sessions else [])])
    ends = set(run.ended.values())
    if "asked" in ends:
        return "asked"
    if "stopped" in ends:
        return "stopped"
    if run.failure:
        raise _fail(run_id, job_id, run.failure)
    return None


async def run_notes(run_id: int, job_id: Optional[int] = None, *, model: Any = None,
                    sessions: tuple[str, ...] = agent.SESSIONS, max_steps: Optional[int] = None) -> None:
    """Run the notes stage. Raises NotesFailed when it fails. `model` replaces the factory's, for tests."""
    if _waiting(run_id):
        logger.info("Run %s: the notes stage waits for an answer to the run's scope question.", run_id)
        return
    if stop_requested(run_id):
        _stopped(run_id, job_id)
        return
    logger.info("Run %s: the notes stage starts.", run_id)
    record: dict = {"run_id": run_id, "sessions": []}
    try:
        _stage(run_id, "working")
        model_id = settings.read()["models"]["extraction"]
        while True:
            ended = await _sessions(run_id, job_id, model_id, model, sessions, max_steps, record)
            if ended != "asked" or _waiting(run_id):
                break
            # The answer came in before the last session ended: start again, every session with fresh deps.
            record["restarts"] = record.get("restarts", 0) + 1
            _write_record(run_id, record)
            _event(run_id, job_id, "notice", "The scope question was answered while the notes agent was stopping, "
                                             "so it starts again from the notes already placed.")
            logger.info("Run %s: the notes stage starts again after an answer that came in mid-step.", run_id)
    except agent.CannotStart as exc:
        raise _fail(run_id, job_id, str(exc)) from exc
    except NotesFailed:
        raise
    except Exception as exc:
        logger.exception("Run %s: the notes stage hit an unexpected error.", run_id)
        raise _fail(run_id, job_id, "The notes agent stopped on an unexpected error.") from exc
    if ended == "asked":
        logger.info("Run %s: the notes stage waits for the answer to a scope question.", run_id)
        return
    if ended == "stopped":
        _stopped(run_id, job_id)
        return
    deps, _ = agent.build_deps(run_id, "placing")
    with db.connect() as conn:
        found = coverage.status(conn, deps)
    record["coverage"] = {"placed": found.placed, "reports": found.reported, "open": found.open}
    record["usage"] = model_usage.run_totals(run_id, "notes")
    _write_record(run_id, record)
    if deps.notes_list and not found.placed and not found.reported:
        raise _fail(run_id, job_id, "No note was placed or reported.")
    _stage(run_id, "done")
    _event(run_id, job_id, "done", f"The notes are placed: {found.placed} of {len(deps.notes_list)} listed note(s) "
                                   f"placed, {found.reported} report(s), {len(found.open)} point(s) open.",
           {**record["coverage"], "open": len(found.open), **record["usage"]})
    logger.info("Run %s: the notes stage is done: %s placed, %s reports, %s open.", run_id, found.placed,
                found.reported, len(found.open))


@handler(NOTES_JOB)
async def notes_job(job: Job) -> None:
    await run_notes(int(job.run_id), job.id)

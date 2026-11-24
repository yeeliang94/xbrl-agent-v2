"""The `extract` job: the figures agent fills the run's statements. Queued by
`app/runs/extraction.start_extraction` when a person confirms the setup.

One figures agent per entity fills every included statement it has not
finished (SOFP, SOPL, SOCI, SOCIE, SOCF); on a Group run the Group's agent
runs first, then the Company's, each told which columns it fills (step 7;
the live comparison chose one agent for all of an entity's statements over
one per statement). Each agent sees the checks across its statements and
the statements finished before it.

`progress` owns "finished": a statement is finished when the agent's
accepted finish covers it. A retry, a restart or a scope answer fills only
the statements not finished. An agent that fails marks nothing finished, and
the next entity's agent still runs; the stage then fails with one plain
sentence naming the statements left unfinished, and every figure saved is
kept. An agent that completes, or reaches its step or time limit, with
figures saved ends the stage done; statements it did not finish are named in
a notice and stay unfinished. One attempt, as for reading: a failure waits
for a person instead of spending again; a server restart hands the job back
once (`queue.recover_after_restart`), and the agent then starts from the
figures already saved.

When the agent asks a scope question (`app/scope/ask.py`), the stage is
`asking` and the run `needs_answer` until a person answers; the answer
queues this job again (`app/scope/answer.py`). A question still open when
the job is handed back after a restart keeps the stage waiting. A stop
request stops every agent still to come.

Everything is findable by run id: the stage, events, the model calls with
tokens and cost, the agent's transcript, and a record of each agent run's
finish, coverage and usage in the run's folder (all in the traces export).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from app import db
from app.agents import loop
from app.catalog.lookup import run_family
from app.catalog.statements import StatementType
from app.extraction import agent
from app.jobs import queue
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.models import usage as model_usage
from app.runs import status as run_status
from app.runs.events import add_event
from app.settings import store as settings
from app.utils.atomic_io import write_json_atomic
from app.utils.paths import output_dir
from app.extraction import progress
from app.scope.fields import ORDER

logger = logging.getLogger(__name__)

EXTRACT_JOB = "extract"
STAGE = "extract"
SOURCE = "extraction"
STATEMENTS = ORDER   # what is extracted, in this order


class ExtractionFailed(RuntimeError):
    """The stage failed; `str()` is the plain sentence already recorded."""


class StoppedOnRequest(Exception):
    """A person stopped the stage (`POST .../extract/stop`): it ends `stopped`, keeping the figures saved."""


STOPPED_SENTENCE = "Stopped on request; the figures saved so far are kept."


def stop_requested(run_id: int) -> bool:
    """Read before each of the agent's steps, so a stop takes effect between steps."""
    with db.connect() as conn:
        row = conn.execute("SELECT stop_requested FROM stages WHERE run_id = ? AND name = ?",
                           (run_id, STAGE)).fetchone()
    return bool(row and row["stop_requested"])


def _stopped(run_id: int, job_id: Optional[int]) -> None:
    """End the stage `stopped`. The run is in review when it holds figures, else stopped; either can be retried."""
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE stages SET status = 'stopped', finished_at = ?, error = ?, working_on = NULL "
                     "WHERE run_id = ? AND name = ?", (db.now(), STOPPED_SENTENCE, run_id, STAGE))
        run_status.extraction_stopped(conn, run_id, run_status.has_figures(conn, run_id))
    _event(run_id, job_id, "stopped", "Extraction stopped on request. The figures saved so far are kept.",
           model_usage.run_totals(run_id))
    logger.info("Run %s: the extract stage was stopped on request.", run_id)


class WaitingForAnswer(Exception):
    """The agent asked a scope question: the stage waits for a person's answer (`app/scope/`)."""


def _waiting(run_id: int) -> bool:
    """True when the run has an open scope question. Its stage and run are
    kept waiting, also when a server restart hands the job back."""
    with db.connect(immediate=True) as conn:
        if conn.execute("SELECT 1 FROM scope_questions WHERE run_id = ? AND status = 'open'",
                        (run_id,)).fetchone() is None:
            return False
        conn.execute("UPDATE stages SET status = 'asking', error = NULL WHERE run_id = ? AND name = ?",
                     (run_id, STAGE))
        run_status.extraction_asked(conn, run_id)
    return True


def _event(run_id: int, job_id: Optional[int], kind: str, message: str, data: Optional[dict] = None,
           pages=None) -> None:
    try:
        add_event(SOURCE, kind, message, run_id=run_id, job_id=job_id, data=data, pages=pages)
    except Exception:  # noqa: BLE001 - progress rows never end the work
        logger.warning("Could not record an extraction event", exc_info=True)


def targets(conn, run_id: int) -> list[str]:
    """The statements the run's setup includes now, in extraction order."""
    family = run_family(conn, run_id)
    return [s for s in STATEMENTS if family is not None and StatementType(s) in family.template_ids]


NOTHING = "Nothing is extracted: no statement is part of this run."


def start(conn, run_id: int) -> Optional[int]:
    """Queue extraction in the caller's transaction. Returns the job id, or
    None when the setup includes no statement."""
    family = run_family(conn, run_id)
    wanted = targets(conn, run_id)
    stamp = db.now()

    def note(kind: str, message: str) -> None:
        conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, ?, ?, ?)",
                     (run_id, SOURCE, kind, message, stamp))
    if not wanted:
        note("notice", NOTHING)
        return None
    row = conn.execute("SELECT id FROM stages WHERE run_id = ? AND name = ?", (run_id, STAGE)).fetchone()
    if row is None:
        stage_id = int(conn.execute("INSERT INTO stages(run_id, name, status) VALUES (?, ?, 'waiting')",
                                    (run_id, STAGE)).lastrowid)
    else:
        stage_id = int(row["id"])
        conn.execute("UPDATE stages SET status = 'waiting', started_at = NULL, finished_at = NULL, error = NULL, "
                     "working_on = NULL, stop_requested = 0 WHERE id = ?", (stage_id,))
    note("queued", progress.queued(wanted, family.entity_scopes, family.variants))
    return queue.enqueue_in(conn, EXTRACT_JOB, {"statements": wanted}, max_attempts=1, run_id=run_id,
                            stage_id=stage_id)


def _stage(run_id: int, status: str, error: Optional[str] = None) -> None:
    stamp = db.now()
    with db.connect(immediate=True) as conn:
        if status == "working":
            conn.execute("UPDATE stages SET status = 'working', started_at = ?, finished_at = NULL, error = NULL "
                         "WHERE run_id = ? AND name = ?", (stamp, run_id, STAGE))
            run_status.extraction_started(conn, run_id)
        else:
            conn.execute("UPDATE stages SET status = ?, finished_at = ?, error = ?, working_on = NULL "
                         "WHERE run_id = ? AND name = ?", (status, stamp, error, run_id, STAGE))
            (run_status.extraction_done if status == "done" else run_status.extraction_failed)(conn, run_id)


def _fail(run_id: int, job_id: Optional[int], sentence: str) -> ExtractionFailed:
    _stage(run_id, "failed", sentence)
    _event(run_id, job_id, "failed", f"Extraction stopped: {sentence}", model_usage.run_totals(run_id))
    logger.warning("Run %s: the extract stage failed: %s", run_id, sentence)
    return ExtractionFailed(sentence)


class UnitFailed(Exception):
    """One agent run failed; `str()` is its plain sentence. The next entity's agent still runs."""


def _usage_since(run_id: int, before: dict) -> dict:
    """This agent run's own calls, tokens and cost: the run's figures totals now, less those before it."""
    now = model_usage.run_totals(run_id, agent.NAME)
    return {k: (round(v - (before.get(k) or 0), 6) if isinstance(v, float) else v - (before.get(k) or 0))
            if isinstance(v, (int, float)) and not isinstance(v, bool) else v for k, v in now.items()}


def _record(run_id: int, statements: tuple[str, ...], entity: str, outcome: loop.AgentOutcome, deps, bench,
            seconds: float, usage: dict, finished: tuple[str, ...]) -> dict:
    """The agent run's finish, coverage and own usage, kept in the run's folder: `extraction-<statements>.json`,
    the statements joined by `+`, with `-Group` on the Group's run."""
    record = {
        "statement": statements[0], "statements": list(statements), "finished": list(finished), "entity": entity,
        "status": outcome.status, "message": outcome.message, "steps": outcome.steps, "max_steps": deps.max_steps,
        "seconds": round(seconds), "workbench": {"on": bench.on, "why": bench.why, "used": outcome.code_tool_used},
        "usage": usage, "finish": deps.finish, "coverage": deps.coverage, "coverage_open": deps.coverage_open,
        "checks_open": deps.checks_open, "writes": deps.writes,
        "transcript": outcome.transcript_path.name if outcome.transcript_path else None,
    }
    name = "+".join(statements) + ("-Group" if entity != "Company" else "")
    try:
        write_json_atomic(output_dir() / "runs" / f"run-{int(run_id)}" / f"extraction-{name}.json", record)
    except Exception:  # noqa: BLE001 - the stage's own result comes first
        logger.warning("Run %s: could not write the extraction record.", run_id, exc_info=True)
    return record


async def _one(run_id: int, job_id: Optional[int], statements: tuple[str, ...], entity: str, entities,
               model_id: str, model: Any, layouts=None) -> dict:
    """One agent run for one entity's statements. Raises UnitFailed, WaitingForAnswer or StoppedOnRequest."""
    started = time.monotonic()
    before = model_usage.run_totals(run_id, agent.NAME)
    named = progress.what(statements, entity, entities, layouts)
    logger.info("Run %s: the figures agent starts on %s, %s columns, with %s.", run_id, "+".join(statements), entity,
                model_id)
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE stages SET working_on = ? WHERE run_id = ? AND name = ?",
                     (statements[0], run_id, STAGE))
        pages = sorted({p for r in conn.execute(
            f"SELECT pages_json FROM run_statements WHERE run_id = ? AND statement IN "
            f"({', '.join('?' * len(statements))})", (run_id, *statements)) for p in json.loads(r["pages_json"])})
        filled = progress.finished_for(conn, run_id, entity)
    data = {"statement": statements[0], "statements": list(statements), "entity": entity}
    _event(run_id, job_id, "statement", f"Working on the {named}.", data, pages)
    try:
        outcome, deps, bench = await agent.run_figures(run_id, statements, model_id, job_id=job_id, model=model,
                                                       entity=entity, filled=filled,
                                                       should_stop=lambda: stop_requested(run_id))
    except agent.CannotStart as exc:
        raise UnitFailed(str(exc)) from exc
    seconds = time.monotonic() - started
    usage = _usage_since(run_id, before)
    done = progress.covered(deps, outcome.status == loop.COMPLETED and deps.writes > 0)
    record = _record(run_id, statements, entity, outcome, deps, bench, seconds, usage, done)
    logger.info("Run %s: the figures agent ended %s on %s after %s steps in %.0f s, %s save calls, cost $%.4f; "
                "finished: %s.", run_id, outcome.status, named, outcome.steps, seconds, deps.writes,
                usage["cost_usd"] or 0.0, ", ".join(done) or "none")
    if outcome.error:
        logger.warning("Run %s: the figures agent's error: %s", run_id, outcome.error)
    if deps.asked is None and outcome.status == loop.STOPPED and _waiting(run_id):
        logger.info("Run %s: the extract stage stopped for the notes agent's scope question.", run_id)
        raise WaitingForAnswer()
    if deps.asked is not None:
        logger.info("Run %s: the extract stage waits for the answer to scope question %s.", run_id, deps.asked)
        raise WaitingForAnswer()
    if outcome.status == loop.STOPPED and stop_requested(run_id):
        raise StoppedOnRequest()
    if deps.writes == 0:
        raise UnitFailed(f"No figure was saved. {outcome.message}")
    if outcome.status in (loop.FAILED, loop.STOPPED):
        raise UnitFailed(f"{outcome.message.rstrip('.')}; the figures saved so far are kept.")
    open_points = len((deps.finish or {}).get("unresolved") or [])
    details = {"status": outcome.status, "steps": outcome.steps, "seconds": round(seconds), "unresolved": open_points,
               "code_steps": outcome.code_tool_used, **usage}
    if done:
        words = progress.what(done, entity, entities, layouts)
        message = (f"The {words} {'are' if len(done) > 1 else 'is'} filled"
                   + (f", with {open_points} point(s) left open." if open_points else "."))
        with db.connect(immediate=True) as conn:
            progress.mark(conn, run_id, job_id, done, entity, message, details)
    left = tuple(s for s in statements if s not in done)
    if left:
        words = progress.what(left, entity, entities, layouts)
        _event(run_id, job_id, "notice", f"The {words} {'are' if len(left) > 1 else 'is'} partly filled. "
               f"{outcome.message}", {**data, "statements": list(left), **details})
    return record


def _failed_sentence(failed: list[tuple[str, str]]) -> str:
    """One sentence per failed agent run: the statements it left unfinished, then its reason."""
    return " ".join(f"The {named} could not be filled: {reason[:1].lower() + reason[1:]}" for named, reason in failed)


async def run_extraction(run_id: int, job_id: Optional[int] = None, *, model: Any = None,
                         statements: tuple[str, ...] = STATEMENTS) -> None:
    """Extract the run's statements not yet finished, one agent per entity. Raises ExtractionFailed when the
    stage fails. `model` replaces the factory's model, for tests."""
    if _waiting(run_id):
        logger.info("Run %s: the extract stage still waits for an answer to its scope question.", run_id)
        return
    if stop_requested(run_id):   # stopped while it waited to start
        _stopped(run_id, job_id)
        return
    with db.connect() as conn:   # the setup may have changed since the job was queued (a scope answer)
        current = targets(conn, run_id)
        family = run_family(conn, run_id)
        done = progress.finished(conn, run_id)
    statements = tuple(s for s in STATEMENTS if s in statements and s in current)
    entities = family.entity_scopes if family is not None else ()
    layouts = family.variants if family is not None else {}
    todo = progress.todo(statements, entities, done)
    if not todo:
        _stage(run_id, "done")
        _event(run_id, job_id, "notice", NOTHING if not statements else
               "Nothing is left to extract: every statement is already filled.")
        logger.info("Run %s: the extract stage has nothing left to extract.", run_id)
        return
    logger.info("Run %s: the extract stage starts: %s.", run_id,
                "; ".join(f"{'+'.join(s)} {e}" for s, e in todo))
    failed: list[tuple[str, str]] = []
    try:
        _stage(run_id, "working")
        model_id = settings.read()["models"]["extraction"]
        for unit, entity in todo:
            named = progress.what(unit, entity, entities, layouts)
            try:
                await _one(run_id, job_id, unit, entity, entities, model_id, model, layouts)
            except UnitFailed as exc:
                failed.append((named, str(exc)))
                _event(run_id, job_id, "notice", f"The {named} could not be filled: {exc}",
                       {"statements": list(unit), "entity": entity})
                logger.warning("Run %s: the figures agent failed on %s: %s", run_id, named, exc)
            except (WaitingForAnswer, StoppedOnRequest):
                raise
            except Exception:  # noqa: BLE001 - one entity's error never stops the next
                logger.exception("Run %s: the figures agent hit an unexpected error on %s.", run_id, named)
                failed.append((named, "Extraction stopped on an unexpected error."))
                _event(run_id, job_id, "notice", f"The {named} could not be filled: it stopped on an unexpected "
                       "error.", {"statements": list(unit), "entity": entity})
    except WaitingForAnswer:
        return
    except StoppedOnRequest:
        _stopped(run_id, job_id)
        return
    except Exception as exc:
        logger.exception("Run %s: the extract stage hit an unexpected error.", run_id)
        raise _fail(run_id, job_id, "Extraction stopped on an unexpected error.") from exc
    if failed:
        raise _fail(run_id, job_id, _failed_sentence(failed))
    _stage(run_id, "done")
    totals = model_usage.run_totals(run_id)
    with db.connect() as conn:
        ready = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()["status"] == "in_review"
    _event(run_id, job_id, "done", "Extraction is finished. " + (
        "The run is ready for review." if ready else "The run is ready for review once the notes agent ends."),
        totals)
    logger.info("Run %s: the extract stage is done; the run's model calls cost $%.4f in all.", run_id,
                totals["cost_usd"] or 0.0)


@handler(EXTRACT_JOB)
async def extract_job(job: Job) -> None:
    statements = tuple(s for s in job.payload.get("statements", STATEMENTS) if s in STATEMENTS) or STATEMENTS
    await run_extraction(int(job.run_id), job.id, statements=statements)

"""The `review_round` job: the Reviewer works one correction round. Queued
by `rounds.send` when a person presses Send.

Every round reaches a final state here, or in start-up recovery after a
restart (`rounds.recover_after_restart`): done when the Reviewer finished,
stopped on request, failed on anything else (a model failure, the step or
time limit, an unexpected error). Answers and changes made so far are kept
either way. One attempt: a failed round waits for a person to send again.

Recorded by run id: the round row, events (source `review`), the model
calls with tokens and cost, the transcript, the server log's start and end
lines and any traceback, and a record of the finish and the server's change
report in the run's folder (all in the traces export).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from app import db
from app.agents import loop
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.models import usage as model_usage
from app.review import agent, changes, rounds
from app.review.state import NAME
from app.settings import store as settings
from app.utils.atomic_io import write_json_atomic
from app.utils.paths import output_dir

logger = logging.getLogger(__name__)

KEPT = "the answers and changes so far are kept."


class RoundFailed(RuntimeError):
    """The round did not finish; `str()` is the plain sentence already recorded."""


def _record(run_id: int, number: int, outcome: Optional[loop.AgentOutcome], deps, seconds: float) -> dict:
    with db.connect() as conn:
        report = changes.report(conn, run_id, deps.round_id) if deps is not None else None
    record = {"round": number, "status": outcome.status if outcome else None,
              "message": outcome.message if outcome else None, "steps": outcome.steps if outcome else 0,
              "seconds": round(seconds), "usage": model_usage.run_totals(run_id, NAME),
              "finish": deps.finish if deps else None, "answered": deps.answered if deps else {},
              "writes": deps.writes if deps else 0, "report": report,
              "transcript": outcome.transcript_path.name if outcome and outcome.transcript_path else None}
    try:
        write_json_atomic(output_dir() / "runs" / f"run-{int(run_id)}" / f"review-round-{int(number)}.json", record)
    except Exception:  # noqa: BLE001 - the round's own result comes first
        logger.warning("Run %s: could not write the record of correction round %s.", run_id, number, exc_info=True)
    return record


async def run_round(round_id: int, job_id: Optional[int] = None, *, model: Any = None,
                    max_steps: int = agent.MAX_STEPS) -> None:
    """Work one round to a final state. Raises RoundFailed when it did not
    finish. `model` replaces the factory's model, for tests."""
    row = await asyncio.to_thread(rounds.begin, round_id)
    if row is None:
        logger.info("Correction round id %s is not waiting (stopped or ended already); nothing to do.", round_id)
        return
    run_id, number = int(row["run_id"]), int(row["number"])
    started = time.monotonic()
    logger.info("Run %s: correction round %s starts.", run_id, number)
    outcome, deps = None, None
    try:
        model_id = settings.read()["models"]["review"]
        outcome, deps = await agent.run_reviewer(row, model_id, job_id=job_id, model=model, max_steps=max_steps,
                                                 should_stop=lambda: rounds.stop_requested(round_id))
    except agent.CannotStart as exc:
        rounds.end(round_id, "failed", error=str(exc), data=model_usage.run_totals(run_id, NAME))
        logger.warning("Run %s: correction round %s could not start: %s", run_id, number, exc)
        raise RoundFailed(str(exc)) from exc
    except Exception as exc:
        logger.exception("Run %s: correction round %s hit an unexpected error.", run_id, number)
        sentence = f"The round stopped on an unexpected error; {KEPT}"
        rounds.end(round_id, "failed", error=sentence, data=model_usage.run_totals(run_id, NAME))
        raise RoundFailed(sentence) from exc
    try:
        _settle(round_id, run_id, number, outcome, deps, time.monotonic() - started)
    except RoundFailed:
        raise
    except Exception as exc:   # the round still ends, and the run leaves correcting
        logger.exception("Run %s: correction round %s failed while its result was recorded.", run_id, number)
        sentence = f"The round stopped on an unexpected error; {KEPT}"
        rounds.end(round_id, "failed", error=sentence, data=model_usage.run_totals(run_id, NAME))
        raise RoundFailed(sentence) from exc


def _settle(round_id: int, run_id: int, number: int, outcome: loop.AgentOutcome, deps, seconds: float) -> None:
    """Record the round and end it as its outcome says."""
    record = _record(run_id, number, outcome, deps, seconds)
    usage = record["usage"]
    if outcome.error:
        logger.warning("Run %s: the Reviewer's error in round %s: %s", run_id, number, outcome.error)
    logger.info("Run %s: correction round %s ended %s after %s steps in %.0f s, %s write calls, cost $%.4f.",
                run_id, number, outcome.status, outcome.steps, seconds, deps.writes, usage["cost_usd"] or 0.0)
    if outcome.status == loop.COMPLETED:
        counts = (record["report"] or {}).get("counts", {})
        summary = deps.outline.readable((deps.finish or {}).get("summary") or "") or "Finished."   # read by a person
        rounds.end(round_id, "done", summary=summary, data={**counts, **usage},
                   message=f"Correction round {number} is finished: {counts.get('changed', 0)} of "
                           f"{counts.get('comments', 0)} comment(s) changed.")
        return
    if outcome.status == loop.STOPPED:
        rounds.end(round_id, "stopped", error=f"Stopped on request; {KEPT}", data=usage)
        return
    if outcome.status in (loop.STEP_LIMIT, loop.TIME_LIMIT) and _work_complete(deps):
        # Every comment is answered and the checks ran after the last change: only the finish is missing.
        counts = (record["report"] or {}).get("counts", {})
        rounds.end(round_id, "done", summary=outcome.message, data={**counts, **usage},
                   message=f"Correction round {number} is finished at its limit: {counts.get('changed', 0)} of "
                           f"{counts.get('comments', 0)} comment(s) changed.")
        return
    sentence = f"{outcome.message.rstrip('.')}; {KEPT}"
    rounds.end(round_id, "failed", error=sentence, data=usage)
    raise RoundFailed(sentence)


def _work_complete(deps) -> bool:
    return (deps is not None and all(c in deps.answered for c in deps.comment_ids)
            and (deps.writes == 0 or deps.checked_at == deps.writes))


@handler(rounds.JOB)
async def review_job(job: Job) -> None:
    await run_round(int(job.payload["round_id"]), job.id)

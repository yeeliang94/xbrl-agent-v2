"""The `investigate` job: after a fill that left figures without a cell, the investigating agent looks for
their places (step 12). Queued by the fill job (`app/filing/job.py`) when `store.to_place` finds any. One
attempt: a failed investigation leaves the receipt as it was, with its one plain sentence.

Recorded by run id: the fill's `investigation` status, events (source `fill`), the model calls, the agent's
transcript and `runs/run-<id>/investigation-<fill>.json`."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app import db
from app.agents import loop
from app.filing.investigate import agent, store
from app.jobs import queue
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.models import usage as model_usage
from app.runs.events import add_event
from app.settings import store as settings
from app.utils.atomic_io import write_json_atomic
from app.utils.paths import output_dir

logger = logging.getLogger(__name__)

JOB = "investigate"
SOURCE = "fill"
UNEXPECTED = "The investigation stopped on an unexpected error; the receipt stands as it is."


def start(conn, fill_id: int, run_id: int) -> int:
    """Queue the investigation of one fill, in the caller's transaction."""
    conn.execute("UPDATE fills SET investigation = 'queued', investigation_error = NULL WHERE id = ?", (fill_id,))
    conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, 'queued', ?, ?)",
                 (run_id, SOURCE, "Looking for places in the template for the figures the fill could not place.",
                  db.now()))
    return queue.enqueue_in(conn, JOB, {"fill_id": fill_id}, max_attempts=1, run_id=run_id)


def _status(fill_id: int, status: str, error: Optional[str] = None) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE fills SET investigation = ?, investigation_error = ? WHERE id = ?",
                     (status, error, fill_id))


def _event(run_id: int, job_id: Optional[int], kind: str, message: str, data: dict) -> None:
    try:
        add_event(SOURCE, kind, message, run_id=run_id, job_id=job_id, data=data)
    except Exception:  # noqa: BLE001 - progress rows never end the work
        logger.warning("Could not record an investigation event", exc_info=True)


def _record_not_found(deps) -> None:
    """The figures the agent says it looked for and found no single cell for, with its reason. A figure it
    never reached is not recorded, so the receipt never says "no place found" for it."""
    named = {n["figure"].strip().upper(): n["why"] for n in (deps.finish or {}).get("not_found") or []}
    with db.connect(immediate=True) as conn:
        for fid, why in named.items():
            line = deps.figures.get(fid)
            if line is not None and fid not in deps.proposed:
                store.not_found(conn, deps.fill_id, line, " ".join(why.split()) or store.NOT_FOUND)


async def run_investigation(fill_id: int, run_id: int, job_id: Optional[int] = None, *, model: Any = None,
                            max_steps: Optional[int] = None) -> None:
    """Investigate one fill to a final status: done, or failed with one plain sentence."""
    logger.info("Run %s: the investigation of fill %s starts.", run_id, fill_id)
    _status(fill_id, "working")
    started = time.monotonic()
    try:
        model_id = settings.read()["models"]["extraction"]
        outcome, deps = await agent.run(fill_id, model_id, job_id=job_id, model=model, max_steps=max_steps)
    except agent.CannotStart as exc:
        _status(fill_id, "failed", str(exc))
        _event(run_id, job_id, "failed", f"The template was not investigated: {exc}", {"fill_id": fill_id})
        return
    except Exception:
        logger.exception("Run %s: the investigation of fill %s hit an unexpected error.", run_id, fill_id)
        _status(fill_id, "failed", UNEXPECTED)
        _event(run_id, job_id, "failed", UNEXPECTED, {"fill_id": fill_id})
        return
    record = {"run_id": run_id, **agent.record(outcome, deps), "seconds": round(time.monotonic() - started),
              "usage": model_usage.run_totals(run_id, agent.tools.NAME)}
    try:
        write_json_atomic(output_dir() / "runs" / f"run-{int(run_id)}" / f"investigation-{int(fill_id)}.json", record)
    except Exception:  # noqa: BLE001 - the investigation's own result comes first
        logger.warning("Run %s: could not write the investigation record.", run_id, exc_info=True)
    _record_not_found(deps)
    logger.info("Run %s: the investigation of fill %s ended %s after %s steps: %s of %s figure(s) placed.",
                run_id, fill_id, outcome.status, outcome.steps, len(deps.proposed), len(deps.figures))
    if outcome.status == loop.FAILED and not deps.proposed:
        sentence = f"{outcome.message.rstrip('.')}; the receipt stands as it is."
        _status(fill_id, "failed", sentence)
        _event(run_id, job_id, "failed", f"The template investigation stopped: {sentence}", {"fill_id": fill_id})
        return
    _status(fill_id, "done")
    _event(run_id, job_id, "investigated",
           f"Places proposed for {len(deps.proposed)} of {len(deps.figures)} figure(s); check them before they are "
           "saved." if deps.proposed else "No place was found in the template for the figures the fill left out.",
           {"fill_id": fill_id, "proposed": len(deps.proposed), "figures": len(deps.figures)})


@handler(JOB)
async def investigate_job(job: Job) -> None:
    await run_investigation(int(job.payload["fill_id"]), int(job.run_id), job.id)

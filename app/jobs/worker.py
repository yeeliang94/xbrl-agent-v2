"""The one worker loop and the handler registry.

A handler is a named function registered in code with `@handler("name")`. It
receives the claimed `Job`. It may be a plain or an async function. Raising
any exception counts as a failed attempt.

The worker runs at most two jobs at once, never two of the same kind, so the
figures agent and the notes agent work side by side (decision record 4,
item 6). Each job's writes stay short; the note renderer draws one picture
at a time behind its own lock.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
from typing import Awaitable, Callable, Union

from app.db import copies
from app.jobs import queue
from app.records import server_log

logger = logging.getLogger(__name__)

Handler = Callable[[queue.Job], Union[None, Awaitable[None]]]
_HANDLERS: dict[str, Handler] = {}

POLL_SECONDS = 0.5
MAX_AT_ONCE = 2
# Saving a job's outcome is retried this often, this far apart, before the
# job is left for start-up recovery. The handler is never run again for it.
SAVE_ATTEMPTS = 3
SAVE_RETRY_SECONDS = 0.5


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if kind in _HANDLERS:
            raise ValueError(f"A handler named {kind!r} is already registered.")
        _HANDLERS[kind] = fn
        return fn
    return register


async def _save_outcome(job: queue.Job, save: Callable[..., object], *args, **kwargs) -> None:
    for attempt in range(1, SAVE_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(save, *args, **kwargs)
            return
        except sqlite3.Error as exc:
            if attempt == SAVE_ATTEMPTS:
                logger.error(
                    "Could not save the outcome of job %s (%s) after %s attempts: %s. "
                    "It stays working until start-up recovery.", job.id, job.kind, attempt, exc)
                return
            logger.warning("Saving the outcome of job %s failed, trying again: %s", job.id, exc)
            await asyncio.sleep(SAVE_RETRY_SECONDS)


async def run_once(*, retry_delay: float = queue.RETRY_DELAY_SECONDS, busy_kinds=()) -> bool:
    """Claim and run one due job. Returns False when none was due."""
    job = await asyncio.to_thread(queue.claim, tuple(busy_kinds))
    if job is None:
        return False
    await _run(job, retry_delay)
    return True


async def _run(job: queue.Job, retry_delay: float = queue.RETRY_DELAY_SECONDS) -> None:
    fn = _HANDLERS.get(job.kind)
    # Lines logged while this job works carry its run (app/records/server_log.py).
    token = server_log.RUN_ID.set(job.run_id)
    try:
        if fn is None:
            raise LookupError(f"No handler is registered for jobs of kind {job.kind!r}.")
        if inspect.iscoroutinefunction(fn):
            await fn(job)
        else:
            await asyncio.to_thread(fn, job)
    except asyncio.CancelledError:
        # Shutting down mid-job: the next start-up marks it for retry.
        raise
    except Exception as exc:  # noqa: BLE001 - every handler failure is recorded
        logger.warning("Job %s (%s) failed: %s", job.id, job.kind, exc)
        await _save_outcome(job, queue.fail, job.id, f"{type(exc).__name__}: {exc}",
                            retry_delay=retry_delay)
    else:
        await _save_outcome(job, queue.complete, job.id)
    finally:
        server_log.RUN_ID.reset(token)
        copies.request_save()   # on Azure, a copy of the database soon after each job


async def run_forever(stop: asyncio.Event, *, max_at_once: int = MAX_AT_ONCE) -> None:
    """The worker loop started with the app: up to `max_at_once` jobs at a
    time, each of a different kind. On stop, jobs still working are
    cancelled; start-up recovery hands them back."""
    running: dict[asyncio.Task, str] = {}
    try:
        while not stop.is_set():
            job = None
            if len(running) < max_at_once:
                try:
                    job = await asyncio.to_thread(queue.claim, tuple(running.values()))
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - a database hiccup must not end the loop
                    logger.exception("The job worker hit an error; it will keep going.")
            if job is not None:
                running[asyncio.create_task(_run(job))] = job.kind
                continue
            waits = [*running, asyncio.ensure_future(stop.wait())]
            done, _ = await asyncio.wait(waits, timeout=POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            waits[-1].cancel()
            for task in [t for t in running if t.done()]:
                running.pop(task)
                if not task.cancelled() and task.exception() is not None:
                    logger.error("A job task ended on an error: %s", task.exception())
    finally:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)


# Register the built-in handlers.
from app.jobs import handlers as _handlers  # noqa: E402,F401

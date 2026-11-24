"""The `read` job: transcribe the pages not yet read, then let the Reader
map the document. Queued by `documents.store.start_reading`.

On success the run moves to `setup`. On failure the `read` stage is failed
with one plain sentence and every finished page is kept, so a retry reads
only what is missing. One page failing does not fail the stage; the Reader
is told the page could not be transcribed and can look at its picture. An
unexpected error stops every page first (`transcribe.transcribe_pages`),
so the stage is marked failed only once nothing is still running.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app import db
from app.documents import store as documents
from app.jobs.queue import Job
from app.jobs.worker import handler
from app.models import usage as model_usage
from app.reading import reader, store, transcribe
from app.reading.map_schema import statement_name
from app.runs.events import add_event
from app.settings import store as settings

logger = logging.getLogger(__name__)

SOURCE = "reading"


class ReadingFailed(RuntimeError):
    """The stage failed; `str()` is the plain sentence already recorded."""


def _event(run_id: int, job_id: Optional[int], kind: str, message: str, data: Optional[dict] = None,
           pages=None) -> None:
    try:
        add_event(SOURCE, kind, message, run_id=run_id, job_id=job_id, data=data, pages=pages)
    except Exception:  # noqa: BLE001 - progress rows never end the work
        logger.warning("Could not record a reading event", exc_info=True)


def _fail(run_id: int, job_id: Optional[int], sentence: str) -> ReadingFailed:
    with db.connect(immediate=True) as conn:
        store.stage_failed(conn, run_id, sentence)
    _event(run_id, job_id, "failed", f"Reading stopped: {sentence}")
    logger.warning("Run %s: the read stage failed: %s", run_id, sentence)
    return ReadingFailed(sentence)


async def _transcribe(run_id: int, job_id: Optional[int], model_id: str, model: Any) -> None:
    with db.connect() as conn:
        waiting = store.pages_to_read(conn, run_id)
        path, total = documents.pdf_path(conn, run_id)
    if not waiting:
        return
    _event(run_id, job_id, "transcribing", f"Reading {total} pages." if len(waiting) == total
           else f"Reading the {len(waiting)} pages not yet read.")
    started = time.monotonic()
    done = 0

    async def on_page(result: transcribe.PageResult) -> None:
        nonlocal done
        done += 1

        def save() -> None:
            with db.connect(immediate=True) as conn:
                store.save_page(conn, run_id, result.page, result.content, result.error)
        await transcribe.drained(save)
        if result.content is None:
            message = f"Page {result.page} could not be read: {result.error}"
        elif result.blank:
            message = f"Page {result.page} is blank."
        else:
            message = f"Read page {result.page} of {total}."
        await transcribe.drained(_event, run_id, job_id, "page", message,
                                 {"page": result.page, "calls": result.calls, "done": done, "of": len(waiting)})

    try:
        agent = transcribe.build_agent(model_id, model)
    except ValueError as exc:   # the model could not be built, e.g. a missing key
        raise _fail(run_id, job_id, str(exc)) from exc
    summary = await transcribe.transcribe_pages(agent, model_id, str(path), waiting, total, run_id=run_id,
                                                on_page=on_page)
    with db.connect() as conn:
        progress = store.progress(conn, run_id)["pages"]
    logger.info("Run %s: transcription finished in %.0f s: %s read, %s blank, %s failed.", run_id,
                time.monotonic() - started, summary.read, summary.blank, len(summary.failed))
    if progress["read"] == 0 and summary.failed:   # nothing but blank pages and failures
        first = next(iter(summary.failed.values()), "No page could be read.")
        raise _fail(run_id, job_id, f"No page could be read. {first}")
    failed = f"; {progress['failed']} could not be read" if progress["failed"] else ""
    _event(run_id, job_id, "transcribed",
           f"Read {progress['read'] + progress['blank']} of {progress['total']} pages{failed}.",
           model_usage.run_totals(run_id, transcribe.SOURCE))


def _report_map(run_id: int, job_id: Optional[int], doc_map: dict, open_points: list[str]) -> None:
    for st in doc_map["statements"]:
        name = statement_name(st["statement"], st.get("layout"))
        if st["found"]:
            pages = " and ".join(str(p) for p in st["pages"])
            unsure = ", unsure of the layout" if st["unsure"] else ""
            _event(run_id, job_id, "found", f"{name} on page{'s' if len(st['pages']) > 1 else ''} {pages}{unsure}.",
                   pages=st["pages"])
        else:
            _event(run_id, job_id, "found", f"{name} is not printed.")
    notes = doc_map["notes"]
    if notes:
        first, last = min(n["first_page"] for n in notes), max(n["last_page"] for n in notes)
        _event(run_id, job_id, "found", f"{len(notes)} notes, pages {first} to {last}.", pages=[first, last])
    if open_points:
        _event(run_id, job_id, "notice", f"{len(open_points)} point(s) about the notes list are left for review.",
               {"open_points": open_points})


async def _map(run_id: int, job_id: Optional[int], model_id: str, model: Any) -> None:
    with db.connect() as conn:
        path, total = documents.pdf_path(conn, run_id)
        deps = reader.ReaderDeps(run_id=run_id, pdf_path=str(path), page_count=total,
                                 contents=store.page_contents(conn, run_id), pages=store.map_pages(conn, run_id))
    started = time.monotonic()
    outcome = await reader.run_reader(deps, model_id, job_id=job_id, model=model)
    logger.info("Run %s: the Reader ended %s after %s steps in %.0f s.", run_id, outcome.status, outcome.steps,
                time.monotonic() - started)
    if deps.saved is None:
        raise _fail(run_id, job_id, f"The Reader did not save the document map. {outcome.message}")
    _report_map(run_id, job_id, deps.saved, deps.open_points)


async def run_reading(run_id: int, job_id: Optional[int] = None, *, transcription_model: Any = None,
                      reader_model: Any = None) -> None:
    """Read the run's document. Raises ReadingFailed when the stage fails.
    The two models replace the factory's, for tests."""
    logger.info("Run %s: the read stage starts.", run_id)
    with db.connect(immediate=True) as conn:
        store.stage_working(conn, run_id)
    model_id = settings.read()["models"]["reading"]
    try:
        await _transcribe(run_id, job_id, model_id, transcription_model)
        await _map(run_id, job_id, model_id, reader_model)
    except ReadingFailed:
        raise
    except Exception as exc:
        logger.exception("Run %s: the read stage hit an unexpected error.", run_id)
        raise _fail(run_id, job_id, "Reading stopped on an unexpected error.") from exc
    with db.connect(immediate=True) as conn:
        store.stage_done(conn, run_id)
    _event(run_id, job_id, "finished", "The document map is saved. Setup is ready.",
           model_usage.run_totals(run_id))
    logger.info("Run %s: the read stage is done.", run_id)


@handler(documents.READ_JOB)
async def read_job(job: Job) -> None:
    await run_reading(int(job.run_id), job.id)

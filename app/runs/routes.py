"""The run list, a run's activity feed, confirming its setup and deleting a run."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response

from app import db
from app.auth import store as auth_store
from app.auth.deps import current_user, require_admin
from app.auth.store import User
from app.runs import deleting, events, extraction, listing, setup, store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _not_found(detail: str = "There is no such run.") -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": detail})


def run_dicts(conn, rows) -> list[dict]:
    """`Run` objects (docs/api-contract.md) for run-list rows."""
    names = auth_store.names_for(conn, (r["owner_email"] for r in rows))
    return [{**dict(r), "owner_name": names.get(r["owner_email"], "")} for r in rows]


@router.get("/runs")
def list_runs(q: str = Query(""), status: str = Query(""), standard: str = Query(""),
              updated_since: str = Query(""), mine: bool = Query(False), page: int = Query(0, ge=0),
              per_page: int = Query(listing.PER_PAGE, ge=1, le=listing.MAX_PER_PAGE),
              user: User = Depends(current_user)):
    """One page of the run list, newest first, after the search and the filters."""
    filters = listing.filters_from(q, status, standard, updated_since, user.email if mine else "")
    with db.connect() as conn:
        try:
            rows, total, page = listing.page_of_runs(conn, filters, page, per_page)
        except listing.ListRefused as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc)})
        return {"runs": run_dicts(conn, rows), "total": total, "page": page, "per_page": per_page}


@router.get("/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(current_user)):
    """One run: its run-list row, its statements, a failure, what extraction is on and any open question."""
    with db.connect() as conn:
        try:
            store.open_run(conn, run_id, user)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        return {"run": {**run_dicts(conn, [store.run_row(conn, run_id)])[0], **store.run_detail(conn, run_id)}}


@router.get("/runs/{run_id}/events")
def run_events(run_id: int, after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=events.MAX_LIMIT),
               hide_internal: bool = Query(False), user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            store.open_run(conn, run_id, user)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        return events.page_events(conn, run_id, after_id, limit, hide_internal=hide_internal)


@router.get("/runs/{run_id}/events/{event_id}")
def run_event(run_id: int, event_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            store.open_run(conn, run_id, user)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        event = events.event_detail(conn, run_id, event_id)
    return {"event": event} if event else _not_found("There is no such event in this run.")


@router.post("/runs/{run_id}/setup")
def confirm_setup(run_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    from app.documents import store as documents

    with db.connect(immediate=True) as conn:
        try:
            run = store.open_run(conn, run_id, user)
            _, page_count = documents.pdf_path(conn, run_id)
            company = setup.confirm(conn, run, body, page_count, user.email)
        except (store.RunNotFound, documents.NoDocument) as exc:
            return _not_found(str(exc))
        except setup.SetupRefused as exc:
            return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
        return {"run": run_dicts(conn, [store.run_row(conn, run_id)])[0], "company": company}


@router.get("/runs/{run_id}/deletion")
def deletion(run_id: int, user: User = Depends(current_user)):
    """What deleting this run would remove, and whether this person may delete it now."""
    with db.connect() as conn:
        try:
            run = store.open_run(conn, run_id, user)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        refused = None
        try:
            deleting.check(conn, run, user)
        except deleting.DeleteRefused as exc:
            refused = {"code": exc.code, "detail": str(exc)}
        return {"allowed": refused is None, "refused": refused, **deleting.contents(conn, run_id)}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, user: User = Depends(current_user)):
    """The run's owner or an admin deletes a run that is not working: its rows, then its files."""
    with db.connect(immediate=True) as conn:
        try:
            deleting.delete_run(conn, store.open_run(conn, run_id, user), user)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        except deleting.DeleteRefused as exc:
            return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    store.remove_run_files(run_id)
    return Response(status_code=204)


@router.get("/admin/drafts")
def abandoned_drafts(older_than_days: int = Query(30), admin: User = Depends(require_admin)):
    """How many runs still at setup have not been touched for this many days."""
    try:
        days = deleting.draft_days(older_than_days)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    with db.connect() as conn:
        return {"older_than_days": days, "count": len(deleting.abandoned_drafts(conn, days))}


@router.post("/admin/drafts/clear")
def clear_drafts(body: Any = Body(None), admin: User = Depends(require_admin)):
    """Delete every run still at setup that has not been touched for the chosen number of days."""
    try:
        days = deleting.draft_days(body.get("older_than_days") if isinstance(body, dict) else None)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    with db.connect(immediate=True) as conn:
        run_ids = deleting.clear_drafts(conn, days, admin)
    for run_id in run_ids:
        store.remove_run_files(run_id)
    return {"older_than_days": days, "cleared": len(run_ids)}


@router.post("/runs/{run_id}/extract/stop", status_code=202)
def stop_extraction(run_id: int, user: User = Depends(current_user)):
    """Stop a running extraction between the agent's steps, keeping every figure saved so far."""
    with db.connect(immediate=True) as conn:
        try:
            store.open_run(conn, run_id, user)
            at_once = extraction.stop_extraction(conn, run_id)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        except extraction.NothingToStop as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})
        logger.info("Run %s: %s asked extraction to stop (%s).", run_id, user.email,
                    "stopped at once" if at_once else "before the next step")
        return {"run": run_dicts(conn, [store.run_row(conn, run_id)])[0]}


@router.post("/runs/{run_id}/extract/retry", status_code=202)
def retry_extraction(run_id: int, user: User = Depends(current_user)):
    """Start a failed extraction again on the same run, keeping every figure saved so far."""
    with db.connect(immediate=True) as conn:
        try:
            store.open_run(conn, run_id, user)
            job_id = extraction.retry_extraction(conn, run_id)
        except store.RunNotFound as exc:
            return _not_found(str(exc))
        except extraction.NothingToRetry as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})
        logger.info("Run %s: %s queued the failed extraction again (job %s).", run_id, user.email, job_id)
        return {"run": run_dicts(conn, [store.run_row(conn, run_id)])[0]}

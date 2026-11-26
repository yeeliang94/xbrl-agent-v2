"""Reading progress, the document map and the suggested setup
(docs/api-contract.md, "Reading")."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.documents import store as documents
from app.reading import store
from app.runs import store as runs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.get("/{run_id}/read")
def read_progress(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return {"read": store.progress(conn, run_id)}
        except (runs.RunNotFound, documents.NoDocument) as exc:
            return _error(404, str(exc))


@router.post("/{run_id}/read/retry", status_code=202)
def retry_reading(run_id: int, user: User = Depends(current_user)):
    with db.connect(immediate=True) as conn:
        try:
            runs.open_run(conn, run_id, user)
            store.retry(conn, run_id)
            return {"read": store.progress(conn, run_id)}
        except (runs.RunNotFound, documents.NoDocument) as exc:
            return _error(404, str(exc))
        except store.NothingToRetry as exc:
            return _error(409, str(exc))


@router.post("/{run_id}/read/stop", status_code=202)
def stop_reading(run_id: int, user: User = Depends(current_user)):
    """Stop the reading: no new page and no new step starts, and every page read is kept."""
    with db.connect(immediate=True) as conn:
        try:
            runs.open_run(conn, run_id, user)
            at_once = store.request_stop(conn, run_id)
            logger.info("Run %s: %s asked the reading to stop (%s).", run_id, user.email,
                        "stopped at once" if at_once else "after the calls under way")
            return {"read": store.progress(conn, run_id)}
        except (runs.RunNotFound, documents.NoDocument) as exc:
            return _error(404, str(exc))
        except store.NothingToStop as exc:
            return _error(409, str(exc))


@router.get("/{run_id}/map")
def document_map(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return {"map": store.document_map(conn, run_id)}
        except (runs.RunNotFound, documents.NoDocument, store.NoMap) as exc:
            return _error(404, str(exc))


@router.get("/{run_id}/setup")
def suggested_setup(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return {"setup": store.suggested_setup(conn, run_id)}
        except (runs.RunNotFound, documents.NoDocument, store.NoMap) as exc:
            return _error(404, str(exc))

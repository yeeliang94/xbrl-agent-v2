"""Statement views, figure edits and checks for one run (`docs/api-contract.md`, Step 1).

A person's edits go through the same figure store functions agents use.
"""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.checks.runner import read_checks
from app.figures import store, views
from app.runs import store as runs

router = APIRouter(prefix="/api/runs/{run_id}")


class EditBody(BaseModel):
    concept_uuid: str
    period: str
    entity_scope: str
    value: Optional[float] = None
    dimensions: Optional[dict[str, str]] = None
    page: Optional[int] = None
    printed_label: Optional[str] = None
    reason: Optional[str] = None


class MoveBody(BaseModel):
    to_concept_uuid: str
    whole_row: bool = False


class RestoreBody(BaseModel):
    history_id: int


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _person(user: User) -> store.Actor:
    return store.Actor("person", user.email)


def _change(run_id: int, user: User, work):
    """Open the run, make one change in one write transaction, or say why not."""
    try:
        with db.connect(immediate=True) as conn:
            runs.open_run(conn, run_id, user)
            result = work(conn)
            runs.touch(conn, run_id)
            return result
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except store.Refused as exc:
        return _error(422, str(exc))


@router.get("/statements/{statement}")
def get_statement(run_id: int, statement: str, order: str = Query("report"),
                  user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return views.statement_view(conn, run_id, statement, order)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        except views.StatementNotInRun as exc:
            return _error(404, str(exc))
        except views.ViewError as exc:
            return _error(422, str(exc))


@router.post("/figures")
def edit_figure(run_id: int, body: EditBody, user: User = Depends(current_user)):
    if body.value is not None and not math.isfinite(body.value):
        return _error(422, store.NOT_A_NUMBER)
    def work(conn):
        count = conn.execute("SELECT page_count FROM documents WHERE run_id = ?", (run_id,)).fetchone()
        if body.page is not None and count is not None and not 1 <= body.page <= count[0]:
            raise store.Refused(f"The page must be within the document's {count[0]} pages.")
        return {"figure": store.edit_by_person(
            conn, run_id, _person(user), concept_uuid=body.concept_uuid, period=body.period,
            entity_scope=body.entity_scope, value=body.value, dimensions=body.dimensions, page=body.page,
            printed_label=body.printed_label, reason=body.reason)}
    return _change(run_id, user, work)


@router.post("/figures/{figure_id}/move")
def move_figure(run_id: int, figure_id: int, body: MoveBody, user: User = Depends(current_user)):
    return _change(run_id, user, lambda conn: {"figures": store.move_figure(
        conn, run_id, figure_id, body.to_concept_uuid, _person(user), whole_row=body.whole_row)})


@router.post("/figures/{figure_id}/confirm")
def confirm_figure(run_id: int, figure_id: int, user: User = Depends(current_user)):
    return _change(run_id, user, lambda conn: {"figure": store.confirm_figure(conn, run_id, figure_id, _person(user))})


@router.post("/figures/{figure_id}/restore")
def restore_figure(run_id: int, figure_id: int, body: RestoreBody, user: User = Depends(current_user)):
    def work(conn):
        entry = conn.execute("SELECT figure_id FROM figure_history WHERE run_id = ? AND id = ?",
                             (run_id, body.history_id)).fetchone()
        if entry is None or entry["figure_id"] != figure_id:
            raise store.Refused("There is no such change in this figure's history.")
        return {"figure": store.restore_figure(conn, run_id, body.history_id, _person(user))}
    return _change(run_id, user, work)


@router.get("/figures/{figure_id}/history")
def figure_history(run_id: int, figure_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return {"history": store.figure_history(conn, run_id, figure_id)}
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        except store.Refused as exc:
            return _error(404, str(exc))


@router.get("/checks")
def get_checks(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        return {"checks": read_checks(conn, run_id)}

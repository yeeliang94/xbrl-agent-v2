"""Redoing one statement of a run, and what the run cost (docs/api-contract.md, "Run controls")."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.runs import cost, redo, store
from app.runs.routes import run_dicts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs/{run_id}")


class RedoBody(BaseModel):
    keep_mine: bool = True


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.get("/statements/{statement}/redo")
def redo_preview(run_id: int, statement: str, user: User = Depends(current_user)):
    """Whether the statement can be redone now, and the lines a person edited or confirmed."""
    with db.connect() as conn:
        try:
            return {"redo": redo.preview(conn, store.open_run(conn, run_id, user), statement)}
        except (store.RunNotFound, redo.NoSuchStatement) as exc:
            return _error(404, str(exc))


@router.post("/statements/{statement}/redo", status_code=202)
def redo_statement(run_id: int, statement: str, body: RedoBody = RedoBody(), user: User = Depends(current_user)):
    """Clear the statement and let the figures agent fill it again. The other statements are left as they are."""
    with db.connect(immediate=True) as conn:
        try:
            done = redo.start(conn, store.open_run(conn, run_id, user), statement, body.keep_mine, user.email)
        except (store.RunNotFound, redo.NoSuchStatement) as exc:
            return _error(404, str(exc))
        except redo.RedoRefused as exc:
            return _error(409, str(exc))
        store.touch(conn, run_id)
        logger.info("Run %s: %s asked for the %s to be redone (%s figures cleared, %s lines kept).", run_id,
                    user.email, statement, done["cleared"], done["kept"])
        return {"run": run_dicts(conn, [store.run_row(conn, run_id)])[0], **done}


@router.get("/cost")
def run_cost(run_id: int, user: User = Depends(current_user)):
    """The run's cost and time, per agent."""
    with db.connect() as conn:
        try:
            store.open_run(conn, run_id, user)
        except store.RunNotFound as exc:
            return _error(404, str(exc))
        return {"cost": cost.run_cost(conn, run_id)}

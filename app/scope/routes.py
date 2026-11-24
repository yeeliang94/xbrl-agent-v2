"""A run's scope question: read it, answer it (docs/api-contract.md, Step 5b).
Anyone who may open the run may answer it, as for the rest of the run."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.documents import store as documents
from app.runs import routes as run_routes, store as runs
from app.scope import answer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs/{run_id}")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.get("/question")
def open_question(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        row = answer.open_question(conn, run_id)
        return {"question": answer.public(row) if row else None}


@router.get("/questions")
def all_questions(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        return {"questions": answer.questions(conn, run_id)}


@router.post("/question/answer")
def answer_question(run_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    try:
        with db.connect(immediate=True) as conn:
            run = runs.open_run(conn, run_id, user)
            question = answer.answer(conn, run, body, user.email)
            runs.touch(conn, run_id)
            return {"question": question, "run": run_routes.run_dicts(conn, [runs.run_row(conn, run_id)])[0]}
    except (runs.RunNotFound, documents.NoDocument) as exc:
        return _error(404, str(exc))
    except answer.QuestionRefused as exc:
        return _error(exc.status, str(exc))

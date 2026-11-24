"""A run's reports: list every field, edit one with its revision, clear one,
and read one field's history (`docs/api-contract.md`, Step 10).

A person's changes go through the same report store the reports agent uses.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.notes import source
from app.reading import store as reading
from app.reports import job, store
from app.runs import store as runs

router = APIRouter(prefix="/api/runs/{run_id}/reports")


class EditBody(BaseModel):
    revision: int
    status: Literal["filled", "not_shown", "unsure"] = "filled"
    value: Optional[str] = None
    blocks: list[str] = []          # the narrative: block ids or ranges, such as p12b0-p13b4
    pages: list[int] = []
    reason: str = ""


class ClearBody(BaseModel):
    revision: int
    reason: str = ""


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _person(user: User) -> store.Actor:
    return store.Actor("person", user.email)


def _answer(work, *, write: bool, run_id: int, user: User):
    try:
        with db.connect(immediate=write) as conn:
            runs.open_run(conn, run_id, user)
            result = work(conn)
            if write:
                runs.touch(conn, run_id)
            return result
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except store.FieldNotFound as exc:
        return _error(404, str(exc))
    except store.StaleEdit as exc:
        return _error(409, str(exc))
    except store.Refused as exc:
        return _error(422, str(exc))


def _stage(conn, run_id: int) -> Optional[dict]:
    row = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = ?",
                       (run_id, job.STAGE)).fetchone()
    return {"status": row["status"], "error": row["error"]} if row else None


@router.get("")
def list_reports(run_id: int, user: User = Depends(current_user)):
    return _answer(lambda conn: {"stage": _stage(conn, run_id), "reports": store.run_reports(conn, run_id)},
                   write=False, run_id=run_id, user=user)


@router.get("/{report}/{field}/history")
def field_history(run_id: int, report: str, field: str, user: User = Depends(current_user)):
    return _answer(lambda conn: {"history": store.field_history(conn, run_id, report, field)},
                   write=False, run_id=run_id, user=user)


@router.patch("/{report}/{field}")
def edit_field(run_id: int, report: str, field: str, body: EditBody, user: User = Depends(current_user)):
    def work(conn):
        sources: list[tuple[int, int]] = []
        if body.status == "filled" and body.blocks:
            sources, problem = source.parse_refs(body.blocks, reading.page_contents(conn, run_id))
            if problem:
                raise store.Refused(problem)
        write = store.FieldWrite(body.status, body.value, sources, body.pages, body.reason)
        return {"field": store.save_field(conn, run_id, report, field, write, _person(user),
                                          expected_revision=body.revision)}
    return _answer(work, write=True, run_id=run_id, user=user)


@router.post("/{report}/{field}/clear")
def clear_field(run_id: int, report: str, field: str, body: ClearBody, user: User = Depends(current_user)):
    return _answer(lambda conn: {"field": store.clear_field(conn, run_id, report, field, _person(user),
                                                            expected_revision=body.revision, reason=body.reason)},
                   write=True, run_id=run_id, user=user)

"""Attach, read and remove a run's starting workbook (`docs/api-contract.md`, Step 10d)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.runs import store as runs
from app.scoring.routes import MAX_UPLOAD_BYTES, _read_capped
from app.starting import store, workbook
from app.workbook.xlsx_cells import WorkbookUnreadable

router = APIRouter(prefix="/api/runs/{run_id}")
_SUFFIXES = (".xlsx", ".xlsm")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.post("/starting-workbook")
def attach(run_id: int, file: UploadFile = File(...), user: User = Depends(current_user)):
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(_SUFFIXES):
        return _error(422, "Choose an .xlsx or .xlsm workbook.")
    data = _read_capped(file)
    if data is None:
        return _error(413, f"This file is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data:
        return _error(422, "This file is empty.")
    try:
        with db.connect() as conn:
            runs.open_run(conn, run_id, user)
        return {"starting_workbook": store.attach(run_id, data, filename=filename, uploaded_by=user.email)}
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except store.TooLate as exc:
        return _error(409, str(exc))
    except (WorkbookUnreadable, workbook.Refused) as exc:
        return _error(422, str(exc))


@router.get("/starting-workbook")
def read(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        return {"starting_workbook": store.record(conn, run_id)}


@router.delete("/starting-workbook")
def remove(run_id: int, user: User = Depends(current_user)):
    try:
        with db.connect() as conn:
            runs.open_run(conn, run_id, user)
        store.remove(run_id, user.email)
    except (runs.RunNotFound, store.NoWorkbook) as exc:
        return _error(404, str(exc))
    except store.TooLate as exc:
        return _error(409, str(exc))
    return Response(status_code=204)

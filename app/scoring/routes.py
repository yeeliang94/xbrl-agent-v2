"""Attach a filled workbook to a run and read its comparison (`docs/api-contract.md`, Step 2).

Rebuilt from v1 `api/human_file.py`. v1 refused runs that had not finished;
v2 scores any run, because the comparison is worked out on every read.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.runs import store as runs
from app.scoring import attached
from app.scoring.workbook_read import NothingMatches
from app.workbook.xlsx_cells import WorkbookUnreadable

router = APIRouter(prefix="/api/runs/{run_id}")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # as v1: an mTool workbook is a few hundred KB
_CHUNK = 1024 * 1024
_SUFFIXES = (".xlsx", ".xlsm")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _read_capped(upload: UploadFile) -> bytes | None:
    """The upload, or None once it passes the limit. Never holds more than the limit plus a chunk."""
    chunks, total = [], 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/filled-workbook")
def attach_workbook(run_id: int, file: UploadFile = File(...), user: User = Depends(current_user)):
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(_SUFFIXES):
        return _error(422, "Choose an .xlsx or .xlsm workbook.")
    data = _read_capped(file)
    if data is None:
        return _error(413, "This file is over 25 MB.")
    if not data:
        return _error(422, "This file is empty.")
    try:
        with db.connect() as conn:
            runs.open_run(conn, run_id, user)
        return {"workbook": attached.attach(run_id, data, filename=filename, uploaded_by=user.email)}
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except (WorkbookUnreadable, NothingMatches) as exc:
        return _error(422, str(exc))


@router.get("/filled-workbook")
def get_workbook(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        return {"workbook": attached.record(conn, run_id)}


@router.delete("/filled-workbook")
def remove_workbook(run_id: int, user: User = Depends(current_user)):
    try:
        with db.connect() as conn:
            runs.open_run(conn, run_id, user)
        attached.remove(run_id)
    except (runs.RunNotFound, attached.NoWorkbook) as exc:
        return _error(404, str(exc))
    return Response(status_code=204)


@router.get("/comparison")
def get_comparison(run_id: int, user: User = Depends(current_user)):
    try:
        with db.connect() as conn:
            runs.open_run(conn, run_id, user)
        return {"comparison": attached.comparison(run_id)}
    except (runs.RunNotFound, attached.NoWorkbook) as exc:
        return _error(404, str(exc))
    except (WorkbookUnreadable, NothingMatches) as exc:
        return _error(422, str(exc))

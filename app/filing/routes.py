"""Upload an mTool template and fill it (or fill the run's starting workbook),
list a run's fills, read one with its receipt, and download the filled file
(docs/api-contract.md, Step 8 and Step 10g). Every
route opens the run first."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.filing import receipts
from app.filing.investigate import store as placements
from app.runs import store as runs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs/{run_id}/fills")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # as the scoring upload: an mTool workbook is a few hundred KB
_CHUNK = 1024 * 1024
_TYPES = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12"}


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _read_capped(upload: UploadFile) -> bytes | None:
    chunks, total = [], 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", status_code=202)
def start_fill(run_id: int, file: Optional[UploadFile] = File(None), user: User = Depends(current_user)):
    """With `file`, fill that template. Without it, fill the run's starting workbook (step 10g)."""
    data = filename = None
    if file is not None:
        filename = Path(file.filename or "").name
        if Path(filename).suffix.lower() not in receipts.SUFFIXES:
            return _error(422, receipts.WRONG_TYPE)
        data = _read_capped(file)
        if data is None:
            return _error(413, "This file is over 25 MB.")
        if not data:
            return _error(422, "This file is empty.")
    try:
        with db.connect(immediate=True) as conn:
            run = runs.open_run(conn, run_id, user)
            if data is None:
                row = receipts.start_from_starting(conn, run, email=user.email)
            else:
                row = receipts.start(conn, run, data, filename=filename, email=user.email)
            runs.touch(conn, run_id)
            fill = receipts.public(row)
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except receipts.FillRefused as exc:
        return _error(exc.status, str(exc))
    logger.info("Run %s: mTool fill %s is queued by %s%s.", run_id, fill["id"], user.email,
                "" if data is not None else " (the starting workbook)")
    return JSONResponse(status_code=202, content={"fill": fill})


@router.get("")
def list_fills(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        return {"fills": receipts.list_fills(conn, run_id)}


@router.get("/{fill_id}")
def get_fill(run_id: int, fill_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            row = receipts.get_row(conn, run_id, fill_id)
            found = placements.not_found_keys(conn, fill_id) if row["investigation"] == "done" else frozenset()
            return {"fill": receipts.public(row, with_receipt=True, not_found=found,
                                            placements_open=placements.open_count(conn, fill_id))}
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        except receipts.FillRefused as exc:
            return _error(exc.status, str(exc))


@router.get("/{fill_id}/file")
def download_fill(run_id: int, fill_id: int, user: User = Depends(current_user)):
    try:
        with db.connect(immediate=True) as conn:
            runs.open_run(conn, run_id, user)
            row, path = receipts.mark_downloaded(conn, run_id, fill_id)
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except receipts.FillRefused as exc:
        return _error(exc.status, str(exc))
    logger.info("Run %s: mTool fill %s downloaded by %s.", run_id, fill_id, user.email)
    return FileResponse(path, media_type=_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                        filename=receipts.download_name(row))

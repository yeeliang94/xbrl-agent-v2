"""Create a run from an uploaded PDF, Word or Excel file, read its document and draw its pages
(`docs/api-contract.md`, Step 3)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.documents import intake, pdf_viewer, sheets, source_file, store
from app.documents.page_cache import CACHE
from app.runs import store as runs
from app.runs.routes import run_dicts

router = APIRouter(prefix="/api/runs")

# v1's test documents are 15 to 27 MB; a long group report with high-resolution
# scans can be several times that.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024
_CLIP_REFUSAL = "Give the region as four page fractions from 0 to 1: left, top, right, bottom."


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


def _megabytes(size: int) -> int:
    return max(1, round(size / (1024 * 1024)))


@router.post("")
def upload_file(file: UploadFile = File(...), user: User = Depends(current_user)):
    """Start a run from one PDF, Word (.docx) or Excel (.xlsx) file."""
    filename = Path(file.filename or "").name or "document.pdf"
    by_name = source_file.refused_by_name(filename)
    if by_name is not None:
        return _error(422, str(by_name))
    limit = f"The largest file a run can take is {_megabytes(MAX_UPLOAD_BYTES)} MB."
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        return _error(413, f"{filename} is {_megabytes(file.size)} MB. {limit}")
    data = _read_capped(file)
    if data is None:
        return _error(413, f"{filename} is too large. {limit}")
    if not data:
        return _error(422, "This file is empty.")
    try:
        upload = intake.prepare(filename, data)
    except source_file.Refused as exc:
        return _error(422, str(exc))
    with db.connect(immediate=True) as conn:
        run_id = store.create_run(conn, upload, owner_email=user.email)
        return {"run": run_dicts(conn, [runs.run_row(conn, run_id)])[0], "document": store.document(conn, run_id)}


@router.get("/{run_id}/document")
def get_document(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return {"document": store.document(conn, run_id)}
        except (runs.RunNotFound, store.NoDocument) as exc:
            return _error(404, str(exc))


class BringIn(BaseModel):
    sheet: str


@router.get("/{run_id}/sheets/{name}")
def get_sheet(run_id: int, name: str, user: User = Depends(current_user)):
    """One sheet of an Excel run's workbook, as its filled cells."""
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            found = sheets.grid(conn, run_id, name)
        except (runs.RunNotFound, store.NoDocument) as exc:
            return _error(404, str(exc))
    if found is None:
        return _error(404, f"This run has no sheet called {name}.")
    return {"sheet": found}


@router.post("/{run_id}/sheets/bring-in")
def bring_in_sheet(run_id: int, body: BringIn, user: User = Depends(current_user)):
    """Bring a hidden sheet into a run waiting at setup. The run reads the new pages, then waits at setup again."""
    try:
        sheets.bring_in(run_id, user, body.sheet)
        with db.connect() as conn:
            return {"run": run_dicts(conn, [runs.run_row(conn, run_id)])[0], "document": store.document(conn, run_id)}
    except (runs.RunNotFound, store.NoDocument) as exc:
        return _error(404, str(exc))
    except sheets.SheetRefused as exc:
        return _error(409, str(exc))
    except source_file.Refused as exc:
        return _error(422, str(exc))


def _parse_clip(text: str | None) -> pdf_viewer.Clip | None:
    if text is None:
        return None
    parts = text.split(",")
    if len(parts) != 4:
        raise pdf_viewer.BadClip(text)
    return pdf_viewer.validate_clip(tuple(parts))


@router.get("/{run_id}/pages/{page}/image")
def page_image(run_id: int, page: int, clip: str | None = None, user: User = Depends(current_user)):
    try:
        region = _parse_clip(clip)
    except pdf_viewer.BadClip:
        return _error(422, _CLIP_REFUSAL)
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            path, count = store.pdf_path(conn, run_id)
            turn = store.upright_turn(conn, run_id, page)
        except (runs.RunNotFound, store.NoDocument) as exc:
            return _error(404, str(exc))
    if not 1 <= page <= count:
        return _error(404, f"This document has no page {page}.")
    cap = pdf_viewer.DEFAULT_DPI
    png = CACHE.get_or_render(str(path), page, cap, region,
                              lambda: pdf_viewer.render_page_png(str(path), page, cap=cap, clip=region, rotate=turn),
                              rotate=turn)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

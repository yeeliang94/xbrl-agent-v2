"""Create a run from an uploaded PDF, read its document and draw its pages
(`docs/api-contract.md`, Step 3)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.documents import pdf_check, pdf_viewer, store
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


@router.post("")
def upload_pdf(file: UploadFile = File(...), user: User = Depends(current_user)):
    filename = Path(file.filename or "").name or "document.pdf"
    if pdf_check.is_word(filename):
        return _error(422, pdf_check.WORD_REFUSAL)
    data = _read_capped(file)
    if data is None:
        return _error(413, "This file is over 100 MB.")
    if not data:
        return _error(422, "This file is empty.")
    if pdf_check.is_word(filename, data):
        return _error(422, pdf_check.WORD_REFUSAL)
    try:
        pages = pdf_check.inspect_pdf(data)
    except pdf_check.NotAPdf as exc:
        return _error(422, str(exc))
    with db.connect(immediate=True) as conn:
        run_id = store.create_run_from_pdf(conn, data, pages, filename=filename, owner_email=user.email)
        return {"run": run_dicts(conn, [runs.run_row(conn, run_id)])[0], "document": store.document(conn, run_id)}


@router.get("/{run_id}/document")
def get_document(run_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return {"document": store.document(conn, run_id)}
        except (runs.RunNotFound, store.NoDocument) as exc:
            return _error(404, str(exc))


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

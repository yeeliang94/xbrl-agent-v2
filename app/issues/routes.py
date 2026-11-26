"""Report an issue (anyone signed in) and the admin's list of them
(`docs/api-contract.md`, "Report an issue").

A report made from a run keeps that run's number, so an admin can download
the run's traces straight from the issue. Updating, closing, reopening and
deleting an issue, and downloading traces from one, each write an audit row.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app import db
from app.auth import store as accounts
from app.auth.deps import current_user, require_admin
from app.auth.store import User
from app.issues import store
from app.records import routes as records_routes, traces
from app.runs import store as runs

router = APIRouter(prefix="/api/issues")

MAX_TEXT = 4000
MAX_NOTE = 4000
MAX_FILE_BYTES = 10 * 1024 * 1024
_CHUNK = 1024 * 1024
_NO_ISSUE = "There is no such issue."


class IssueChange(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _read_capped(upload: UploadFile) -> Optional[bytes]:
    """The upload, or None once it passes the limit."""
    chunks, total = [], 0
    while chunk := upload.file.read(_CHUNK):
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def run_label(row) -> str:
    """The run as a person knows it: its company and year, else its file, else its number."""
    if row["company"]:
        return f"{row['company']}, FY{row['year']}" if row["year"] else row["company"]
    return row["filename"] or f"Run {row['id']}"


@router.post("")
def report_issue(text: str = Form(""), run_id: Optional[int] = Form(None), file: Optional[UploadFile] = File(None),
                 user: User = Depends(current_user)):
    text = text.strip()
    if not text:
        return _error(422, "Say what went wrong.")
    if len(text) > MAX_TEXT:
        return _error(422, f"Keep the report under {MAX_TEXT} characters.")
    data = file_name = None
    if file is not None:
        data = _read_capped(file)
        if data is None:
            return _error(413, "This screenshot is over 10 MB.")
        if store.picture_kind(data) is None:
            return _error(422, "Attach a picture: a PNG, JPEG, GIF or WebP file.")
        file_name = Path(file.filename or "").name[:200] or None
    with db.connect(immediate=True) as conn:
        label = ""
        if run_id is not None:
            try:
                runs.open_run(conn, run_id, user)
            except runs.RunNotFound as exc:
                return _error(404, str(exc))
            label = run_label(runs.run_row(conn, run_id))
        return {"issue": store.create(conn, reporter_email=user.email, text=text, run_id=run_id, run_label=label,
                                      file_name=file_name, file_data=data)}


@router.get("")
def list_issues(status: str = Query("all"), admin: User = Depends(require_admin)):
    with db.connect() as conn:
        return {"issues": store.list_issues(conn, status if status in store.STATUSES else None)}


@router.patch("/{issue_id}")
def change_issue(issue_id: int, body: IssueChange, admin: User = Depends(require_admin)):
    if body.status is not None and body.status not in store.STATUSES:
        return _error(422, "An issue is open or closed.")
    if body.note is not None and len(body.note) > MAX_NOTE:
        return _error(422, f"Keep the note under {MAX_NOTE} characters.")
    with db.connect(immediate=True) as conn:
        issue = store.get(conn, issue_id)
        if issue is None:
            return _error(404, _NO_ISSUE)
        note = body.note.strip() if body.note is not None else None
        status_changed = body.status is not None and body.status != issue["status"]
        note_changed = note is not None and note != issue["note"]
        if status_changed or note_changed:
            store.update(conn, issue_id, status=body.status, note=note)
        if note_changed:
            accounts.add_audit(conn, admin.email, "issue_updated", str(issue_id), {"note": True})
        if status_changed:
            accounts.add_audit(conn, admin.email,
                               "issue_closed" if body.status == "closed" else "issue_reopened", str(issue_id))
        return {"issue": store.get(conn, issue_id)}


@router.delete("/{issue_id}")
def delete_issue(issue_id: int, admin: User = Depends(require_admin)):
    """Removes the report and its screenshot. The run is kept."""
    with db.connect(immediate=True) as conn:
        if store.get(conn, issue_id) is None:
            return _error(404, _NO_ISSUE)
        store.delete(conn, issue_id)
        accounts.add_audit(conn, admin.email, "issue_deleted", str(issue_id))
    store.remove_files(issue_id)
    return Response(status_code=204)


@router.get("/{issue_id}/file")
def issue_file(issue_id: int, admin: User = Depends(require_admin)):
    with db.connect() as conn:
        found = store.file_of(conn, issue_id)
    if found is None:
        return _error(404, "This issue has no screenshot.")
    path, name = found
    kind = store.picture_kind(path.read_bytes()[:16])
    # Always a download, never drawn in the page: the file came from a person.
    return FileResponse(path, media_type=kind[1] if kind else "application/octet-stream", filename=name,
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{issue_id}/traces")
def issue_traces(issue_id: int, admin: User = Depends(require_admin)):
    """The traces zip of the run the issue was reported from, as `GET /api/runs/{id}/traces` builds it."""
    # Built on a read connection: building can take seconds, and the write lock would hold up every agent.
    with db.connect() as conn:
        issue = store.get(conn, issue_id)
        if issue is None:
            return _error(404, _NO_ISSUE)
        run_id = issue["run_id"]
        if run_id is None:
            return _error(404, "This issue has no run, or its run was deleted.")
        path = traces.build(conn, run_id, include_pdf=False)
    with db.connect(immediate=True) as conn:
        accounts.add_audit(conn, admin.email, "issue_traces_downloaded", str(issue_id), {"run_id": run_id})
    return records_routes._send_and_remove(path, f"run-{int(run_id)}-traces.zip")

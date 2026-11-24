"""Downloads of what was recorded (docs/api-contract.md, "Traces" and
"Records on the Settings page")."""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app import db
from app.auth.deps import current_user, require_admin
from app.auth.store import User
from app.records import server_log, traces
from app.runs import store as runs
from app.utils.paths import output_dir, safe_entry_path, safe_path

router = APIRouter(prefix="/api")

USAGE_COLUMNS = ("day", "run_id", "run", "model", "calls", "failed_calls", "input_tokens", "cached_tokens",
                 "output_tokens", "cost_usd")
_USAGE_SQL = (
    "SELECT substr(m.created_at, 1, 10) AS day, m.run_id, COALESCE(c.name, d.filename, '') AS run, m.model, "
    "COUNT(*) AS calls, SUM(m.error IS NOT NULL) AS failed_calls, SUM(m.input_tokens) AS input_tokens, "
    "SUM(m.cached_tokens) AS cached_tokens, SUM(m.output_tokens) AS output_tokens, "
    "ROUND(COALESCE(SUM(m.cost_usd), 0), 6) AS cost_usd "
    "FROM model_calls m LEFT JOIN runs r ON r.id = m.run_id LEFT JOIN companies c ON c.id = r.company_id "
    "LEFT JOIN documents d ON d.run_id = m.run_id "
    "GROUP BY day, m.run_id, m.model ORDER BY day, m.run_id, m.model")


def _send_and_remove(path: Path, filename: str) -> FileResponse:
    return FileResponse(path, media_type="application/zip", filename=filename,
                        background=BackgroundTask(lambda: safe_entry_path(path).unlink(missing_ok=True)))


@router.get("/runs/{run_id}/traces")
def run_traces(run_id: int, include_pdf: int = Query(0, ge=0, le=1), user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
        except runs.RunNotFound as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc)})
        path = traces.build(conn, run_id, include_pdf=bool(include_pdf))
    return _send_and_remove(path, f"run-{int(run_id)}-traces.zip")


@router.get("/settings/records/logs")
def server_logs(admin: User = Depends(require_admin)):
    folder = safe_path(output_dir() / "tmp")
    folder.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="server-logs-", suffix=".zip", dir=folder)
    os.close(handle)
    path = safe_path(name)
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for log in server_log.log_files():
                zf.write(log, log.name)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return _send_and_remove(path, "server-logs.zip")


@router.get("/settings/records/usage")
def usage(admin: User = Depends(require_admin)):
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(_USAGE_SQL)]
    text = traces.csv_text(USAGE_COLUMNS, rows)
    # A byte-order mark lets Excel on Windows read the file as UTF-8.
    return Response(content=("﻿" + text).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="usage.csv"'})

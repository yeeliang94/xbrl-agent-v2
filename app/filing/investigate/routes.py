"""The places the investigating agent proposed for one fill, and a person's Use or Skip of each, which saves
the used ones for the template and fills it again (docs/api-contract.md, Step 12)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.filing import receipts
from app.filing.investigate import store
from app.runs import store as runs
from app.workbook.toolkit.book import Book, row_label

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs/{run_id}/fills/{fill_id}/placements")

NOT_READY = "The places are not ready yet."
DECIDED = "These places were already checked."
NOT_THESE = "Choose places from this fill's list."


class Decision(BaseModel):
    use: list[int]


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.get("")
def list_placements(run_id: int, fill_id: int, user: User = Depends(current_user)):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            fill = receipts.get_row(conn, run_id, fill_id)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        except receipts.FillRefused as exc:
            return _error(exc.status, str(exc))
        return {"investigation": fill["investigation"], "error": fill["investigation_error"],
                "placements": [store.public(r) for r in store.for_fill(conn, fill_id)]}


@router.post("", status_code=202)
def decide(run_id: int, fill_id: int, body: Decision, user: User = Depends(current_user)):
    """Save the places a person chose to use for this template, skip the rest, and fill the template again."""
    try:
        with db.connect(immediate=True) as conn:
            run = runs.open_run(conn, run_id, user)
            fill = receipts.get_row(conn, run_id, fill_id)
            if fill["investigation"] != "done":
                return _error(409, NOT_READY)
            open_ids = {r["id"] for r in store.for_fill(conn, fill_id) if r["status"] == "open"}
            if not open_ids:
                return _error(409, DECIDED)
            if not set(body.use) <= open_ids:
                return _error(422, NOT_THESE)
            template = Book(receipts.file_path(fill["template_path"]))
            used = store.decide(conn, fill, set(body.use), user.email,
                                lambda sheet, row: row_label(template.sheet(sheet), row))
            # Nothing used changes nothing: the receipt stands, with its reasons, and no fill is queued.
            row = receipts.start_again(conn, run, fill, email=user.email) if used else fill
            runs.touch(conn, run_id)
            new = receipts.public(row)
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except receipts.FillRefused as exc:
        return _error(exc.status, str(exc))
    logger.info("Run %s: %s place(s) of fill %s used by %s; fill %s is queued.", run_id, used, fill_id, user.email,
                new["id"])
    return JSONResponse(status_code=202, content={"fill": new, "used": used})

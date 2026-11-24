"""Comments, correction rounds and the "Needs you" list for one run
(docs/api-contract.md, Step 5a). Every route opens the run first."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.figures import store as figures
from app.review import changes, comments, needs_you, rounds, undo
from app.runs import store as runs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs/{run_id}")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _do(run_id: int, user: User, work: Callable, *, write: bool = True, status: int = 200):
    """Open the run, do the work in one transaction, or say why not."""
    try:
        with db.connect(immediate=write) as conn:
            run = runs.open_run(conn, run_id, user)
            result = work(conn, run)
            if write:
                runs.touch(conn, run_id)
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except (comments.CommentRefused, rounds.RoundRefused) as exc:
        return _error(exc.status, str(exc))
    except figures.Refused as exc:
        return _error(422, str(exc))
    if result is None:
        return Response(status_code=204)
    return result if status == 200 else JSONResponse(status_code=status, content=result)


def _body(body: Any) -> dict:
    return body if isinstance(body, dict) else {}


# Comments ---------------------------------------------------------------------

@router.get("/comments")
def list_comments(run_id: int, status: Optional[list[str]] = Query(None), user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"comments": comments.list_comments(conn, run_id, status or [])},
               write=False)


@router.post("/comments")
def add_comment(run_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"comment": comments.add_person_comment(conn, run, body, user.email)},
               status=201)


@router.delete("/comments/{comment_id}")
def remove_comment(run_id: int, comment_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: comments.remove(conn, run_id, comment_id))


@router.post("/comments/accept-all")
def accept_all(run_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"comments": comments.accept_all(conn, run_id, user.email)})


@router.post("/comments/{comment_id}/reply")
def reply(run_id: int, comment_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"comment": comments.reply(
        conn, run_id, comment_id, _body(body).get("text"), user.email)})


@router.post("/comments/{comment_id}/accept")
def accept(run_id: int, comment_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"comment": comments.accept(conn, run_id, comment_id, user.email)})


@router.post("/comments/{comment_id}/done")
def mark_done(run_id: int, comment_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"comment": comments.mark_done(conn, run_id, comment_id, user.email)})


@router.post("/comments/{comment_id}/undo")
def undo_comment(run_id: int, comment_id: int, user: User = Depends(current_user)):
    def work(conn, run):
        undone, put_back, notes_back = undo.undo(conn, run_id, comment_id, user.email)
        logger.info("Run %s: comment %s undone (%s comment(s), %s figure(s) and %s note(s) put back).", run_id,
                    comment_id, len(undone), len(put_back), len(notes_back))
        # A guidance line added from an undone comment stays in the company's guidance; say so, so the person
        # can take it out too (restore the version before it).
        kept = [{"comment_id": c["id"], "company_id": run["company_id"], "version": c["guidance_version"]}
                for c in undone if c["guidance_status"] == "added"]
        return {"comments": undone, "figures": put_back, "notes": notes_back, "guidance_line_kept": kept}
    return _do(run_id, user, work)


# Rounds -----------------------------------------------------------------------

@router.post("/rounds")
def send_round(run_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"round": rounds.public(conn, rounds.send(
        conn, run, user.email, _body(body).get("client_id")))}, status=202)


@router.get("/rounds")
def list_rounds(run_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: {"rounds": rounds.list_rounds(conn, run_id),
                                                 "accept_all": comments.acceptable(conn, run_id)}, write=False)


@router.get("/rounds/{round_id}")
def get_round(run_id: int, round_id: int, user: User = Depends(current_user)):
    def work(conn, run):
        row = rounds.get_row(conn, run_id, round_id)
        return {"round": rounds.public(conn, row), "report": changes.report(conn, run_id, round_id)}
    return _do(run_id, user, work, write=False)


@router.post("/rounds/{round_id}/stop")
def stop_round(run_id: int, round_id: int, user: User = Depends(current_user)):
    def work(conn, run):
        logger.info("Run %s: %s asked correction round id %s to stop.", run_id, user.email, round_id)
        return {"round": rounds.public(conn, rounds.stop(conn, run_id, round_id))}
    return _do(run_id, user, work)


# Needs you --------------------------------------------------------------------

@router.get("/needs-you")
def get_needs_you(run_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: needs_you.needs_you(conn, run_id), write=False)


@router.post("/needs-you/alike/accept")
def accept_alike(run_id: int, user: User = Depends(current_user)):
    return _do(run_id, user, lambda conn, run: needs_you.accept_alike(conn, run_id, user.email))

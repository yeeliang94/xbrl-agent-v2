"""Firm and company guidance, and adding a Reviewer's proposed line
(docs/api-contract.md, Step 5b).

Company guidance: anyone who may open one of that company's runs reads and
changes it (`runs.open_company`). Firm guidance: everyone signed in reads
it; only an admin changes it.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app import db
from app.auth.deps import current_user, require_admin
from app.auth.store import User
from app.guidance import store
from app.review import comments
from app.runs import store as runs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _do(work: Callable, *, write: bool):
    try:
        with db.connect(immediate=write) as conn:
            return work(conn)
    except (runs.RunNotFound, runs.CompanyNotFound) as exc:
        return _error(404, str(exc))
    except (store.GuidanceRefused, comments.CommentRefused) as exc:
        return _error(exc.status, str(exc))


def _full(conn, company_id: Optional[int]) -> dict:
    return {"guidance": store.latest(conn, company_id), "versions": store.versions(conn, company_id)}


def _company(conn, company_id: int, user: User) -> dict:
    company = runs.open_company(conn, company_id, user)
    return {"id": company["id"], "name": company["name"]}


# Company guidance -------------------------------------------------------------

@router.get("/companies/{company_id}/guidance")
def company_guidance(company_id: int, user: User = Depends(current_user)):
    return _do(lambda conn: {"company": _company(conn, company_id, user), **_full(conn, company_id)}, write=False)


@router.get("/companies/{company_id}/guidance/versions/{number}")
def company_version(company_id: int, number: int, user: User = Depends(current_user)):
    def work(conn):
        _company(conn, company_id, user)
        return {"guidance": store.version(conn, company_id, number)}
    return _do(work, write=False)


def _change(company_id: Optional[int], action: Callable, body: Any, user: User, what: str):
    def work(conn):
        company = _company(conn, company_id, user) if company_id is not None else None
        saved = action(conn, company_id, body, user.email)
        logger.info("%s guidance: %s saved version %s (%s).", "Company %s" % company_id if company else "Firm",
                    user.email, saved["version"], what)
        return {**({"company": company} if company else {}), **_full(conn, company_id)}
    return _do(work, write=True)


@router.put("/companies/{company_id}/guidance")
def save_company_guidance(company_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    return _change(company_id, store.save, body, user, "typed")


@router.post("/companies/{company_id}/guidance/restore")
def restore_company_guidance(company_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    return _change(company_id, store.restore, body, user, "restored")


# Firm guidance ----------------------------------------------------------------

@router.get("/guidance/firm")
def firm_guidance(user: User = Depends(current_user)):
    return _do(lambda conn: _full(conn, None), write=False)


@router.get("/guidance/firm/versions/{number}")
def firm_version(number: int, user: User = Depends(current_user)):
    return _do(lambda conn: {"guidance": store.version(conn, None, number)}, write=False)


@router.put("/guidance/firm")
def save_firm_guidance(body: Any = Body(None), user: User = Depends(require_admin)):
    return _change(None, store.save, body, user, "typed")


@router.post("/guidance/firm/restore")
def restore_firm_guidance(body: Any = Body(None), user: User = Depends(require_admin)):
    return _change(None, store.restore, body, user, "restored")


# A run's guidance and a Reviewer's proposed line ------------------------------

@router.get("/runs/{run_id}/guidance")
def run_guidance(run_id: int, user: User = Depends(current_user)):
    """The guidance an agent on this run would be given now: the firm's and the run's company's. Before
    setup is confirmed, the company is the existing one the Reader's suggested name matches, if any."""
    def work(conn):
        run = runs.open_run(conn, run_id, user)
        company_id, matched = run["company_id"], False
        if company_id is None:
            from app.reading import store as reading
            from app.runs.setup import find_company

            saved = reading.saved_map(conn, run_id)
            found = find_company(conn, ((saved or {}).get("company") or {}).get("value") or "")
            company_id, matched = (int(found["id"]), True) if found is not None else (None, False)
        return {"firm": store.latest(conn, None),
                "company": store.latest(conn, company_id) if company_id is not None else None,
                "company_id": company_id, "company_from_suggestion": matched}
    return _do(work, write=False)


def _proposal(run_id: int, comment_id: int, user: User, act: Callable):
    def work(conn):
        run = runs.open_run(conn, run_id, user)
        comment = comments.row(conn, run_id, comment_id)
        if run["company_id"] is None:
            raise store.GuidanceRefused("This run has no company yet, so it has no company guidance.", 409)
        result = act(conn, run, comment)
        runs.touch(conn, run_id)
        return {**result, "comment": comments.get(conn, run_id, comment_id)}
    return _do(work, write=True)


@router.post("/runs/{run_id}/comments/{comment_id}/guidance")
def add_proposed(run_id: int, comment_id: int, body: Any = Body(None), user: User = Depends(current_user)):
    based_on = body.get("based_on") if isinstance(body, dict) else None

    def act(conn, run, comment):
        saved = store.add_proposed(conn, run["company_id"], comment, based_on, user.email)
        logger.info("Run %s: %s added the proposed line of comment %s to company guidance (version %s).", run_id,
                    user.email, comment_id, saved["version"])
        return _full(conn, run["company_id"])
    return _proposal(run_id, comment_id, user, act)


@router.post("/runs/{run_id}/comments/{comment_id}/guidance/dismiss")
def dismiss_proposed(run_id: int, comment_id: int, user: User = Depends(current_user)):
    def act(conn, run, comment):
        store.dismiss_proposed(conn, comment)
        return {}
    return _proposal(run_id, comment_id, user, act)

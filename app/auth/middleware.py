"""The gate in front of every `/api/*` route. Ported from v1's `server.py`
auth middleware and `auth/middleware.py`.

Open routes: `/api/health` and `/api/auth/login/password`, matched exactly so
a later route cannot be opened by an accidental prefix match. The built
browser app (outside `/api`) is public: it carries no data.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from app import db
from app.auth import config, sessions, store

logger = logging.getLogger(__name__)

OPEN_PATHS = frozenset({"/api/health", "/api/auth/login/password"})

DEV_USER = store.User(email="dev@localhost", name="Dev", is_admin=True)


def is_guarded(path: str) -> bool:
    is_api = path == "/api" or path.startswith("/api/")
    return is_api and path not in OPEN_PATHS


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _write_or_skip(what: str, write) -> bool:
    """Run one small session write in its own write-first transaction. These
    writes are housekeeping (a timestamp, removing a dead session), so a busy
    database skips them instead of failing the request. True when saved."""
    try:
        with db.connect(immediate=True) as conn:
            write(conn)
        return True
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc) and "busy" not in str(exc):
            raise
        logger.info("Skipped %s: the database was busy.", what)
        return False


def _check_session(
    cookie_value: Optional[str],
) -> tuple[Optional[store.Session], Optional[store.User], bool]:
    """The session, its account, and whether its activity time was extended.
    Blocking database work: the middleware runs it off the event loop."""
    with db.connect() as conn:
        session, user, stale_id = sessions.resolve(conn, cookie_value)
    if stale_id is not None:
        _write_or_skip("removing an ended session", lambda c: store.delete_session(c, stale_id))
    bumped = False
    if session is not None and sessions.should_bump_activity(session):
        bumped = _write_or_skip("a session activity bump", lambda c: store.touch_session(c, session.id))
    return session, user, bumped


def _sets_session_cookie(response, name: str) -> bool:
    return any(value.startswith(f"{name}=") for value in response.headers.getlist("set-cookie"))


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not is_guarded(path):
        return await call_next(request)
    if config.dev_bypass_active():
        request.state.user = DEV_USER
        return await call_next(request)

    cookie_name = config.cookie_name()
    cookie_value = request.cookies.get(cookie_name)
    session, user, bumped = await asyncio.to_thread(_check_session, cookie_value)
    if session is None or user is None:
        return _deny(401, "Please sign in.")
    # A temporary password from an admin opens only the /api/auth routes, so
    # the person chooses their own before anything else.
    if user.must_change_password and not path.startswith("/api/auth/"):
        return _deny(403, "Choose a new password to continue.")
    request.state.user = user
    request.state.session_id = session.id
    response = await call_next(request)
    # The session was extended, so the browser's cookie is too. A route that
    # set or cleared the cookie itself (logout, password change) wins.
    if bumped and not _sets_session_cookie(response, cookie_name):
        sessions.set_session_cookie(response, cookie_value)
    return response

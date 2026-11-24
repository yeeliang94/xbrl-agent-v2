"""Session ids, the signed cookie and the sliding idle timeout. Ported from v1
`auth/sessions.py` and `auth/middleware.py::resolve_session`.

The cookie carries `<session id>.<HMAC>`. The signature rejects a forged
cookie before any database read; the id maps to a session row, so logout and
timeout can be revoked.
"""
from __future__ import annotations

import hmac
import secrets
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from typing import Optional

from fastapi import Response

from app.auth import config, store

# Rewrite last_seen_at at most this often; far below the idle timeout.
_MIN_ACTIVITY_BUMP_S = 30


def _sign(session_id: str) -> str:
    return hmac.new(config.session_secret().encode(), session_id.encode(), sha256).hexdigest()


def sign_cookie(session_id: str) -> str:
    return f"{session_id}.{_sign(session_id)}"


def parse_cookie(value: Optional[str]) -> Optional[str]:
    """The session id, or None when the cookie is missing, malformed or forged."""
    if not value or "." not in value:
        return None
    session_id, _, sig = value.partition(".")
    if not session_id or not sig or not hmac.compare_digest(sig, _sign(session_id)):
        return None
    return session_id


def set_session_cookie(response: Response, cookie_value: str) -> None:
    """Set the session cookie with a fresh lifetime of one idle timeout. Used at
    sign-in and each time the middleware extends the session."""
    response.set_cookie(
        key=config.cookie_name(),
        value=cookie_value,
        httponly=True,
        secure=config.secure_cookies(),
        samesite="lax",
        path="/",
        max_age=config.idle_timeout_seconds(),
    )


def create_session(conn: sqlite3.Connection, email: str) -> str:
    """Store a new session and return the signed cookie value."""
    session_id = secrets.token_hex(32)
    store.create_session(conn, session_id, email)
    return sign_cookie(session_id)


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _idle_seconds(session: store.Session) -> Optional[float]:
    last = _parse_time(session.last_seen_at)
    if last is None:
        return None
    return (datetime.now(timezone.utc) - last).total_seconds()


def is_expired(session: store.Session) -> bool:
    idle = _idle_seconds(session)
    return idle is None or idle > config.idle_timeout_seconds()


def should_bump_activity(session: store.Session) -> bool:
    idle = _idle_seconds(session)
    return idle is None or idle >= _MIN_ACTIVITY_BUMP_S


def resolve(
    conn: sqlite3.Connection, cookie_value: Optional[str]
) -> tuple[Optional[store.Session], Optional[store.User], Optional[str]]:
    """The live session and its account, or (None, None, stale id). Reads only.
    The third value is the id of an expired session, or one whose account was
    disabled or deleted, for the caller to remove in its own write."""
    session_id = parse_cookie(cookie_value)
    if session_id is None:
        return None, None, None
    session = store.fetch_session(conn, session_id)
    if session is None:
        return None, None, None
    user = store.fetch_user(conn, session.email)
    if is_expired(session) or user is None or user.disabled:
        return None, None, session_id
    return session, user, None

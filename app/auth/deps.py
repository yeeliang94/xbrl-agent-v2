"""Route dependencies for the signed-in user. The middleware has already
refused a request without a session; these read what it found."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth.store import User


def current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    """The real permission boundary for admin routes. Hiding a screen in the
    browser is only presentation."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can do this.")
    return user

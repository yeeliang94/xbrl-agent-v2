"""Admin user management and the audit log. Route names follow v1
`auth/routes.py`. Every route checks the admin role on the server."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth import passwords, store
from app.auth.deps import require_admin

router = APIRouter(prefix="/api/admin")


class AddUserBody(BaseModel):
    email: str
    name: str = ""
    is_admin: bool = False


class SetAdminBody(BaseModel):
    is_admin: bool


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _is_last_enabled_admin(conn, email: str) -> bool:
    user = store.fetch_user(conn, email)
    return (
        user is not None and user.is_admin and not user.disabled
        and store.count_enabled_admins(conn) <= 1
    )


@router.get("/users")
def list_users(admin: store.User = Depends(require_admin)):
    with db.connect() as conn:
        return {"users": [u.admin_view() for u in store.list_users(conn)]}


@router.post("/users")
def add_user(body: AddUserBody, admin: store.User = Depends(require_admin)):
    """Create an account with a one-time temporary password, returned once."""
    email = store.normalize_email(body.email)
    if not email or "@" not in email:
        return _error(422, "Enter a valid email.")
    temporary = passwords.generate_temporary_password()
    with db.connect(immediate=True) as conn:
        created = store.create_user(
            conn, email, body.name.strip(), passwords.hash_password(temporary),
            is_admin=body.is_admin, must_change_password=True,
        )
        if not created:
            return _error(409, "An account with this email already exists.")
        store.add_audit(conn, admin.email, "user_added", email, {"is_admin": body.is_admin})
        user = store.fetch_user(conn, email)
    return {"user": user.admin_view(), "temporary_password": temporary}


@router.post("/users/{email}/disable")
def disable_user(email: str, admin: store.User = Depends(require_admin)):
    with db.connect(immediate=True) as conn:
        if _is_last_enabled_admin(conn, email):
            return _error(409, "This is the only admin. Make another account an admin first.")
        if not store.set_disabled(conn, email, True):
            return _error(404, "No account has this email.")
        store.add_audit(conn, admin.email, "user_disabled", store.normalize_email(email))
    return {"ok": True}


@router.post("/users/{email}/enable")
def enable_user(email: str, admin: store.User = Depends(require_admin)):
    with db.connect(immediate=True) as conn:
        if not store.set_disabled(conn, email, False):
            return _error(404, "No account has this email.")
        store.add_audit(conn, admin.email, "user_enabled", store.normalize_email(email))
    return {"ok": True}


@router.post("/users/{email}/reset-password")
def reset_password(email: str, admin: store.User = Depends(require_admin)):
    """Issue a new temporary password. The person is signed out everywhere."""
    temporary = passwords.generate_temporary_password()
    with db.connect(immediate=True) as conn:
        user = store.fetch_user(conn, email)
        if user is None:
            return _error(404, "No account has this email.")
        if user.email == admin.email:
            return _error(409, "Change your own password from your account instead.")
        store.set_password(
            conn, user.email, passwords.hash_password(temporary), must_change_password=True
        )
        store.delete_sessions_for(conn, user.email)
        store.add_audit(conn, admin.email, "password_reset", user.email)
    return {"temporary_password": temporary}


@router.post("/users/{email}/admin")
def set_admin(email: str, body: SetAdminBody, admin: store.User = Depends(require_admin)):
    with db.connect(immediate=True) as conn:
        if not body.is_admin and _is_last_enabled_admin(conn, email):
            return _error(409, "This is the only admin. Make another account an admin first.")
        if not store.set_admin(conn, email, body.is_admin):
            return _error(404, "No account has this email.")
        store.add_audit(
            conn, admin.email, "role_changed", store.normalize_email(email),
            {"is_admin": body.is_admin},
        )
        user = store.fetch_user(conn, email)
    return {"user": user.admin_view()}


@router.get("/audit")
def audit_log(
    before: Optional[int] = None, limit: int = 50, admin: store.User = Depends(require_admin)
):
    limit = max(1, min(limit, 200))
    with db.connect() as conn:
        events = store.list_audit(conn, limit=limit, before_id=before)
    return {"events": events, "has_more": len(events) == limit}

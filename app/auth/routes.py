"""Sign-in routes. Route names follow v1 `auth/routes.py`; bodies follow
`docs/api-contract.md`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth import config, lockout, passwords, sessions, store
from app.utils.runtime import on_azure
from app.auth.deps import current_user

router = APIRouter()

# The same words for an unknown email and a wrong password, so the reply does
# not reveal which emails have accounts.
_LOGIN_FAILED = "The email or password is wrong."


class LoginBody(BaseModel):
    email: str
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str = ""
    new_password: str


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _client_ip(request: Request) -> str:
    """The address the lockout counts failures against. On Azure every request comes through
    its front end, which adds the address it saw as the last X-Forwarded-For entry. The
    entries before it are whatever the sender wrote, and uvicorn's `--proxy-headers` takes the
    first one, so a person could dodge the lockout by changing the header on each guess."""
    if on_azure():
        last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if last:
            return _without_port(last)
    return request.client.host if request.client else ""


def _without_port(address: str) -> str:
    """`1.2.3.4:5678` -> `1.2.3.4`, `[2001:db8::1]:443` -> `2001:db8::1`. Azure adds the port,
    and each connection's port differs, so keeping it would make every attempt a new person."""
    if address.startswith("["):
        return address[1:].split("]", 1)[0]
    if address.count(":") == 1:
        return address.split(":", 1)[0]
    return address


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.cookie_name(), httponly=True, secure=config.secure_cookies(),
        samesite="lax", path="/",
    )


@router.post("/api/auth/login/password")
def login_password(request: Request, body: LoginBody):
    ip = _client_ip(request)
    if lockout.seconds_remaining(body.email, ip) > 0:
        return _error(429, "Too many attempts. Try again in a few minutes.")

    with db.connect(immediate=True) as conn:
        user = store.fetch_user(conn, body.email)
        ok = False
        if user is not None and not user.disabled and user.password_hash:
            ok = passwords.verify_password(user.password_hash, body.password)
        else:
            passwords.dummy_verify(body.password)
        if not ok:
            lockout.record_failure(body.email, ip)
            return _error(401, _LOGIN_FAILED)

        lockout.clear(body.email, ip)
        if passwords.needs_rehash(user.password_hash):
            store.set_password(
                conn, user.email, passwords.hash_password(body.password),
                must_change_password=user.must_change_password,
            )
        cookie_value = sessions.create_session(conn, user.email)
        store.record_sign_in(conn, user.email)

    response = JSONResponse(content={"user": user.public()})
    sessions.set_session_cookie(response, cookie_value)
    return response


@router.get("/api/auth/me")
def me(user: store.User = Depends(current_user)):
    return {"user": user.public()}


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request):
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        with db.connect() as conn:
            store.delete_session(conn, session_id)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.post("/api/auth/change-password", status_code=204)
def change_password(
    request: Request, body: ChangePasswordBody, user: store.User = Depends(current_user)
):
    """Change my own password. Asks for the current one, except after an
    admin-issued temporary password, which this session was just opened with."""
    if config.dev_bypass_active():
        return _error(400, "Passwords cannot be changed in development sign-in mode.")
    if len(body.new_password) < passwords.MIN_PASSWORD_LEN:
        return _error(422, f"The new password needs at least {passwords.MIN_PASSWORD_LEN} characters.")

    replacement_cookie = None
    with db.connect(immediate=True) as conn:
        account = store.fetch_user(conn, user.email)
        if account is None:
            return _error(401, "Please sign in.")
        if account.must_change_password:
            if passwords.verify_password(account.password_hash, body.new_password):
                return _error(422, "Choose a password different from the temporary one.")
        elif not passwords.verify_password(account.password_hash, body.current_password):
            # 403, not 401: the session is fine; only the re-check failed.
            return _error(403, "The current password is wrong.")
        store.set_password(
            conn, account.email, passwords.hash_password(body.new_password),
            must_change_password=False,
        )
        if account.must_change_password:
            # No session opened with the temporary password keeps access.
            store.delete_sessions_for(conn, account.email)
            replacement_cookie = sessions.create_session(conn, account.email)

    response = Response(status_code=204)
    if replacement_cookie is not None:
        sessions.set_session_cookie(response, replacement_cookie)
    return response

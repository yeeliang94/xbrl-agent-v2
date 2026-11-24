"""Login settings. Ported from v1 `auth/config.py`. The secrets and switches
come from the environment at call time; the idle timeout and lockout limits
come from the Settings page."""
from __future__ import annotations

import os
import secrets

from app.utils.runtime import on_azure

# The __Host- prefix makes the browser accept the cookie only when it is
# Secure, has Path=/ and no Domain: exactly how it is set in production.
SECURE_COOKIE_NAME = "__Host-xbrl_session"
PLAIN_COOKIE_NAME = "xbrl_session"

# Without SESSION_SECRET, local runs sign cookies with a key only this process
# knows. Production refuses to start without one (app/auth/startup.py).
_LOCAL_SESSION_SECRET = secrets.token_urlsafe(48)


def dev_mode_enabled() -> bool:
    """AUTH_MODE=dev signs everyone in as a local admin. Tests and offline use
    only; production refuses to start with it."""
    return os.environ.get("AUTH_MODE", "").strip().lower() == "dev"


def dev_bypass_active() -> bool:
    return dev_mode_enabled() and not on_azure()


def session_secret() -> str:
    return os.environ.get("SESSION_SECRET") or _LOCAL_SESSION_SECRET


def secure_cookies() -> bool:
    # Azure ends TLS at its front door, so the app may see http. Key on
    # production, not on the request scheme.
    return on_azure()


def cookie_name() -> str:
    return SECURE_COOKIE_NAME if secure_cookies() else PLAIN_COOKIE_NAME


def _login_limit(name: str) -> int:
    # The limits live on the Settings page (owner, 18 November 2026), not in .env.
    from app.settings import store

    return int(store.login_limits()[name])


def idle_timeout_seconds() -> int:
    return _login_limit("idle_timeout_minutes") * 60


def login_max_attempts() -> int:
    return _login_limit("max_attempts")


def login_lockout_seconds() -> int:
    return _login_limit("lockout_minutes") * 60

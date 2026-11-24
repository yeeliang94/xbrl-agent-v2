"""Start-up steps for login: the bootstrap admin and the production refusals.
Ported from v1 `server.py` (`_bootstrap_admin_from_env`,
`_check_auth_startup_config`)."""
from __future__ import annotations

import logging
import os
from typing import Optional

from app import db
from app.auth import config, passwords, store
from app.utils.runtime import on_azure

logger = logging.getLogger(__name__)


def bootstrap_admin_from_env() -> Optional[str]:
    """Create an admin from BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD
    when both are set. An existing account is only ever promoted: its password
    and disabled state are left alone, so a later change is not undone on
    every restart."""
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    if len(password) < passwords.MIN_PASSWORD_LEN:
        logger.warning(
            "BOOTSTRAP_ADMIN_PASSWORD is shorter than %d characters; no admin was created.",
            passwords.MIN_PASSWORD_LEN,
        )
        return "skipped-short-password"
    name = os.environ.get("BOOTSTRAP_ADMIN_NAME", "").strip() or "Local Admin"
    with db.connect(immediate=True) as conn:
        existing = store.fetch_user(conn, email)
        if existing is not None:
            if existing.is_admin:
                return "already-present"
            store.set_admin(conn, email, True)
            return "promoted-existing"
        store.create_user(conn, email, name, passwords.hash_password(password), is_admin=True)
    return "created"


def ensure_dev_user() -> None:
    """With AUTH_MODE=dev (never in production), everyone is signed in as the
    dev user, so that user needs a `users` row: runs and uploads point at it.
    It has no password, so it cannot sign in any other way."""
    if not config.dev_bypass_active():
        return
    from app.auth.middleware import DEV_USER

    with db.connect(immediate=True) as conn:
        conn.execute(
            "INSERT INTO users(email, name, password_hash, is_admin, created_at) VALUES (?, ?, NULL, 1, ?) "
            "ON CONFLICT(email) DO NOTHING", (DEV_USER.email, DEV_USER.name, db.now()))


def check_production_config() -> None:
    """Refuse to start a misconfigured production server. Raises RuntimeError,
    which stops FastAPI's start-up."""
    if not on_azure():
        return
    if config.dev_mode_enabled():
        raise RuntimeError(
            "AUTH_MODE=dev is set in production. Remove it: production always needs a real sign-in."
        )
    if not os.environ.get("SESSION_SECRET"):
        raise RuntimeError(
            "SESSION_SECRET is not set in production. Set it to a long random value before starting."
        )
    with db.connect() as conn:
        if store.count_users(conn, enabled_only=True) == 0:
            raise RuntimeError(
                "No enabled account exists. Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD "
                "for the first start."
            )

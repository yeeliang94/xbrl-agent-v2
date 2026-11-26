"""The only code that reads or writes the users, sessions and audit_log tables.
Ported in design from v1's `db/repository.py` auth helpers."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

from app.db import now


@dataclass
class User:
    email: str
    name: str = ""
    password_hash: Optional[str] = None
    is_admin: bool = False
    disabled: bool = False
    must_change_password: bool = False
    created_at: str = ""
    password_set_at: Optional[str] = None
    last_sign_in_at: Optional[str] = None

    def public(self) -> dict:
        """The contract's `User`. Never the password hash."""
        return {
            "email": self.email,
            "name": self.name,
            "is_admin": self.is_admin,
            "must_change_password": self.must_change_password,
        }

    def admin_view(self) -> dict:
        return {
            **self.public(),
            "disabled": self.disabled,
            "has_password": bool(self.password_hash),
            "created_at": self.created_at,
            "password_set_at": self.password_set_at,
            "last_sign_in_at": self.last_sign_in_at,
        }


@dataclass
class Session:
    id: str
    email: str
    created_at: str
    last_seen_at: str


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _user(row: sqlite3.Row) -> User:
    return User(
        email=row["email"],
        name=row["name"] or "",
        password_hash=row["password_hash"],
        is_admin=bool(row["is_admin"]),
        disabled=bool(row["disabled"]),
        must_change_password=bool(row["must_change_password"]),
        created_at=row["created_at"],
        password_set_at=row["password_set_at"],
        last_sign_in_at=row["last_sign_in_at"],
    )


def fetch_user(conn: sqlite3.Connection, email: str) -> Optional[User]:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
    return _user(row) if row else None


def names_for(conn: sqlite3.Connection, emails) -> dict[str, str]:
    """{email: display name} for the given emails. Unknown emails are left out."""
    wanted = sorted({normalize_email(e) for e in emails if e})
    if not wanted:
        return {}
    marks = ",".join("?" * len(wanted))
    return {r["email"]: r["name"] or "" for r in conn.execute(
        f"SELECT email, name FROM users WHERE email IN ({marks})", wanted)}


def list_users(conn: sqlite3.Connection) -> list[User]:
    return [_user(r) for r in conn.execute("SELECT * FROM users ORDER BY email")]


def create_user(
    conn: sqlite3.Connection,
    email: str,
    name: str,
    password_hash: str,
    *,
    is_admin: bool = False,
    must_change_password: bool = False,
) -> bool:
    """Insert an account. False, and nothing changed, when the email exists."""
    stamp = now()
    cur = conn.execute(
        "INSERT INTO users(email, name, password_hash, is_admin, must_change_password, "
        "created_at, password_set_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(email) DO NOTHING",
        (normalize_email(email), name or "", password_hash, int(is_admin),
         int(must_change_password), stamp, stamp),
    )
    return cur.rowcount > 0


def set_password(
    conn: sqlite3.Connection, email: str, password_hash: str, *, must_change_password: bool
) -> bool:
    cur = conn.execute(
        "UPDATE users SET password_hash = ?, password_set_at = ?, must_change_password = ? "
        "WHERE email = ?",
        (password_hash, now(), int(must_change_password), normalize_email(email)),
    )
    return cur.rowcount > 0


def set_admin(conn: sqlite3.Connection, email: str, is_admin: bool) -> bool:
    cur = conn.execute(
        "UPDATE users SET is_admin = ? WHERE email = ?", (int(is_admin), normalize_email(email))
    )
    return cur.rowcount > 0


def set_disabled(conn: sqlite3.Connection, email: str, disabled: bool) -> bool:
    """Block or re-enable an account. Disabling also ends its sessions now."""
    norm = normalize_email(email)
    cur = conn.execute("UPDATE users SET disabled = ? WHERE email = ?", (int(disabled), norm))
    if disabled and cur.rowcount > 0:
        delete_sessions_for(conn, norm)
    return cur.rowcount > 0


def record_sign_in(conn: sqlite3.Connection, email: str) -> None:
    conn.execute(
        "UPDATE users SET last_sign_in_at = ? WHERE email = ?", (now(), normalize_email(email))
    )


def count_users(conn: sqlite3.Connection, *, enabled_only: bool = False) -> int:
    sql = "SELECT COUNT(*) FROM users" + (" WHERE disabled = 0" if enabled_only else "")
    return int(conn.execute(sql).fetchone()[0])


def count_enabled_admins(conn: sqlite3.Connection) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND disabled = 0"
    ).fetchone()[0])


# Sessions --------------------------------------------------------------

def create_session(conn: sqlite3.Connection, session_id: str, email: str) -> None:
    stamp = now()
    conn.execute(
        "INSERT INTO sessions(id, email, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (session_id, normalize_email(email), stamp, stamp),
    )


def fetch_session(conn: sqlite3.Connection, session_id: str) -> Optional[Session]:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    return Session(row["id"], row["email"], row["created_at"], row["last_seen_at"])


def touch_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now(), session_id))


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_sessions_for(conn: sqlite3.Connection, email: str) -> None:
    conn.execute("DELETE FROM sessions WHERE email = ?", (normalize_email(email),))


# Audit log -------------------------------------------------------------

def add_audit(
    conn: sqlite3.Connection, actor_email: str, action: str, target: str,
    detail: Optional[dict] = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(at, actor_email, action, target, detail_json) VALUES (?, ?, ?, ?, ?)",
        (now(), normalize_email(actor_email), action, target,
         json.dumps(detail) if detail else None),
    )


# The audit screen's "Action" filter. An action belongs to the group whose prefix it starts with.
AUDIT_GROUPS = {
    "users": ("user_", "password_", "role_"),
    "settings": ("setting_",),
    "runs": ("run_", "drafts_"),
    "issues": ("issue_",),
}


def _audit_where(before_id: Optional[int], actor: Optional[str], group: Optional[str]) -> tuple[str, list]:
    clauses, params = [], []
    if before_id is not None:
        clauses.append("e.id < ?")
        params.append(before_id)
    if actor:
        clauses.append("e.actor_email = ?")
        params.append(normalize_email(actor))
    if group:
        prefixes = AUDIT_GROUPS.get(group, ())
        if not prefixes:
            clauses.append("0")
        else:
            clauses.append("(" + " OR ".join("substr(e.action, 1, ?) = ?" for _ in prefixes) + ")")
            for prefix in prefixes:
                params += [len(prefix), prefix]
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_audit(
    conn: sqlite3.Connection, *, limit: int = 50, before_id: Optional[int] = None, offset: int = 0,
    actor: Optional[str] = None, group: Optional[str] = None,
) -> list[dict]:
    """Audit rows, newest first, optionally for one person and one group of actions."""
    where, params = _audit_where(before_id, actor, group)
    sql = (
        "SELECT e.*, a.name AS actor_name, t.name AS target_name FROM audit_log e "
        "LEFT JOIN users a ON a.email = e.actor_email LEFT JOIN users t ON t.email = e.target"
        + where + " ORDER BY e.id DESC LIMIT ? OFFSET ?"
    )
    return [
        {
            "id": r["id"],
            "at": r["at"],
            "actor_email": r["actor_email"],
            "actor_name": r["actor_name"] or "",
            "action": r["action"],
            "target": r["target"],
            "target_name": r["target_name"] or "",
            "detail": json.loads(r["detail_json"]) if r["detail_json"] else None,
        }
        for r in conn.execute(sql, [*params, limit, max(0, offset)])
    ]


def count_audit(conn: sqlite3.Connection, *, actor: Optional[str] = None, group: Optional[str] = None) -> int:
    where, params = _audit_where(None, actor, group)
    return int(conn.execute("SELECT COUNT(*) FROM audit_log e" + where, params).fetchone()[0])


def audit_people(conn: sqlite3.Connection) -> list[dict]:
    """Everyone who has a row in the audit log, for the screen's "Person" filter."""
    return [{"email": r["actor_email"], "name": r["name"] or ""} for r in conn.execute(
        "SELECT DISTINCT e.actor_email, u.name FROM audit_log e LEFT JOIN users u ON u.email = e.actor_email "
        "ORDER BY COALESCE(NULLIF(u.name, ''), e.actor_email)")]

"""App settings: defaults, validation and storage in the `settings` table.

Each top-level field is one row. `route` is not stored: it follows whether a
gateway address is set in `.env`.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

from app import db
from app.auth import store as accounts
from app.models import factory

logger = logging.getLogger(__name__)

ROLES = ("reading", "extraction", "review")
DEFAULT_MODEL = "gpt-6-luna"

DEFAULTS: dict[str, Any] = {
    "models": {role: DEFAULT_MODEL for role in ROLES},
    "code_workbench": True,
    # Claude's sandbox is used with test documents only (decided 18 Nov 2026).
    "claude_sandbox_real_documents": False,
    "house_style": {
        "body_text": "justified",
        "table_font_pt": 10,
        "smallest_table_font_pt": 8,
        "double_underline": "thick_bottom_border",
        "bold_totals": False,
    },
    # Sign-in limits, moved from .env to this page (owner, 18 November 2026).
    # The defaults are v1's: one hour idle, five tries, fifteen minutes locked.
    "login": {"idle_timeout_minutes": 60, "max_attempts": 5, "lockout_minutes": 15},
}

# Allowed range and the name a refusal uses, for each login limit.
_LOGIN_BOUNDS = {
    "idle_timeout_minutes": (5, 1440, "Sign out after idle", "minutes"),
    "max_attempts": (3, 20, "Attempts before lockout", "attempts"),
    "lockout_minutes": (1, 1440, "Lockout time", "minutes"),
}

_CHOICES = {
    "body_text": ("justified", "left"),
    "table_font_pt": (9, 10, 11),
    "smallest_table_font_pt": (8, 9),
    "double_underline": ("thick_bottom_border", "single_bottom_border"),
}


class SettingsError(ValueError):
    """A change that cannot be saved. The message is one plain sentence."""


def _read(conn) -> dict[str, Any]:
    values = copy.deepcopy(DEFAULTS)
    for row in conn.execute("SELECT key, value_json FROM settings"):
        if row["key"] in values:
            stored = json.loads(row["value_json"])
            if isinstance(values[row["key"]], dict):
                values[row["key"]].update(stored)
            else:
                values[row["key"]] = stored
    return {"route": factory.current_setup(), **values}


def read() -> dict[str, Any]:
    with db.connect() as conn:
        return _read(conn)


def _check_models(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - set(ROLES):
        raise SettingsError(f"Models can be set for {', '.join(ROLES)} only.")
    for role, model_id in value.items():
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
            raise SettingsError(f"Choose a model for {role}.")
        if factory.provider_of(model_id) == "unknown":
            raise SettingsError(f"{model_id} is not a GPT or Claude model.")
    return {role: model_id.strip() for role, model_id in value.items()}


def _check_house_style(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - set(DEFAULTS["house_style"]):
        raise SettingsError("That is not a house style setting.")
    for name, choice in value.items():
        if name == "bold_totals":
            if not isinstance(choice, bool):
                raise SettingsError("Bold totals is on or off.")
        elif type(choice) is not type(_CHOICES[name][0]) or choice not in _CHOICES[name]:
            allowed = ", ".join(str(c) for c in _CHOICES[name])
            raise SettingsError(f"{name.replace('_', ' ').capitalize()} must be one of {allowed}.")
    return value


def _check_login(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) - set(_LOGIN_BOUNDS):
        raise SettingsError("That is not a sign-in setting.")
    for name, number in value.items():
        low, high, label, unit = _LOGIN_BOUNDS[name]
        if type(number) is not int or not low <= number <= high:
            raise SettingsError(f"{label} must be a whole number of {unit} from {low} to {high}.")
    return value


# What the audit log calls each setting, and how it words a value.
_SETTING_LABELS = {
    "models": {role: f"{role.capitalize()} model" for role in ROLES},
    "house_style": {"body_text": "Body text", "table_font_pt": "Table font size",
                    "smallest_table_font_pt": "Smallest table font", "double_underline": "Double underline",
                    "bold_totals": "Bold totals"},
    "login": {name: bounds[2] for name, bounds in _LOGIN_BOUNDS.items()},
    "code_workbench": "Code workbench",
    "claude_sandbox_real_documents": "Claude sandbox for real documents",
}


def _count(number: int, unit: str) -> str:
    return f"{number} {unit}" if number == 1 else f"{number} {unit}s"


def _words(group: str, name: str, value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if group == "login" and name.endswith("_minutes"):
        return _count(value // 60, "hour") if value % 60 == 0 else _count(value, "minute")
    if name.endswith("_pt"):
        return f"{value} pt"
    return str(value).replace("_", " ")


def _audit_changes(conn, actor_email: str, current: dict, to_save: dict) -> None:
    """One audit row per setting whose value changed."""
    for group, value in to_save.items():
        pairs = ([(name, current[group].get(name), new) for name, new in value.items()]
                 if isinstance(value, dict) else [("", current[group], value)])
        for name, before, after in pairs:
            if before == after:
                continue
            label = _SETTING_LABELS[group][name] if name else _SETTING_LABELS[group]
            accounts.add_audit(conn, actor_email, "setting_changed", f"{group}.{name}" if name else group,
                               {"setting": label, "from": _words(group, name, before),
                                "to": _words(group, name, after)})


def login_limits() -> dict[str, int]:
    """The sign-in limits, read on each use so a change applies at once. The
    defaults when the database cannot be read, so sign-in never breaks on it."""
    limits = dict(DEFAULTS["login"])
    try:
        with db.connect() as conn:
            row = conn.execute("SELECT value_json FROM settings WHERE key = 'login'").fetchone()
        if row is not None:
            stored = json.loads(row["value_json"])
            limits.update({k: v for k, v in stored.items() if k in limits and type(v) is int})
    except Exception:  # noqa: BLE001 - fall back to the defaults, and say so
        limits = dict(DEFAULTS["login"])
        logger.warning("Could not read the login limits; using the defaults %s.", limits, exc_info=True)
    return limits


def update(changes: dict[str, Any], actor_email: str) -> dict[str, Any]:
    """Validate and save any subset of the changeable fields. Each value that changes adds an audit row."""
    if "route" in changes:
        raise SettingsError("The route follows the gateway address in .env and cannot be changed here.")
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"{sorted(unknown)[0]} is not a setting.")
    # Read, merge and write in one write-first transaction, so two partial
    # saves at the same time cannot undo each other.
    with db.connect(immediate=True) as conn:
        current = _read(conn)
        to_save: dict[str, Any] = {}
        for name, value in changes.items():
            if name == "models":
                to_save[name] = {**current["models"], **_check_models(value)}
            elif name == "house_style":
                to_save[name] = {**current["house_style"], **_check_house_style(value)}
            elif name == "login":
                to_save[name] = {**current["login"], **_check_login(value)}
            elif isinstance(value, bool):
                to_save[name] = value
            else:
                raise SettingsError(f"{name.replace('_', ' ').capitalize()} is on or off.")
        _audit_changes(conn, actor_email, current, to_save)
        stamp = db.now()
        for name, value in to_save.items():
            conn.execute(
                "INSERT INTO settings(key, value_json, updated_at, updated_by) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (name, json.dumps(value), stamp, actor_email),
            )
        return _read(conn)

"""Brute-force lockout for the password login. Ported from v1 `auth/lockout.py`.

Failures are counted per (email, client address). The store is in memory,
which holds because the app runs as one process. On Azure the address is the
one Azure's front end saw (`routes._client_ip`), not one the sender can write.
"""
from __future__ import annotations

import threading
import time

from app.auth import config

_lock = threading.Lock()
# key -> (failure_count, window_started, locked_until), monotonic seconds
_state: dict[tuple[str, str], tuple[int, float, float]] = {}


def _key(email: str, ip: str) -> tuple[str, str]:
    return ((email or "").strip().lower(), ip or "")


def seconds_remaining(email: str, ip: str) -> float:
    with _lock:
        entry = _state.get(_key(email, ip))
    if entry is None:
        return 0.0
    return max(0.0, entry[2] - time.monotonic())


def record_failure(email: str, ip: str) -> None:
    """Count a failed attempt and lock the pair once it reaches the limit. The
    count starts again after one lockout window."""
    now = time.monotonic()
    window = float(config.login_lockout_seconds())
    k = _key(email, ip)
    with _lock:
        _forget_expired(now, window)
        count, started, _ = _state.get(k, (0, now, 0.0))
        if now - started > window:
            count, started = 0, now
        count += 1
        locked_until = now + window if count >= config.login_max_attempts() else 0.0
        _state[k] = (count, started, locked_until)


def _forget_expired(now: float, window: float) -> None:
    """Drop entries whose count window and lock have both run out, so the list
    cannot grow without end. Called with `_lock` held."""
    for k in [k for k, (_, started, until) in _state.items() if now - started > window and now >= until]:
        del _state[k]


def clear(email: str, ip: str) -> None:
    with _lock:
        _state.pop(_key(email, ip), None)


def reset_all() -> None:
    """For tests."""
    with _lock:
        _state.clear()

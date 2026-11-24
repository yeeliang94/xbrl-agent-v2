"""Atomic file writes: write a temporary file in the same folder, then swap it in.

Ported from v1 `utils/atomic_io.py`. A reader never sees half a file. The swap
retries briefly on the file locks Windows virus scanners and sync clients hold.
"""
from __future__ import annotations

import errno
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.utils.paths import PathLike, safe_entry_path, safe_path

REPLACE_ATTEMPTS = 8
INITIAL_RETRY_DELAY_SECONDS = 0.05
MAX_RETRY_DELAY_SECONDS = 0.5

_TRANSIENT_ERRNOS = frozenset({errno.EBUSY, getattr(errno, "ETXTBSY", errno.EBUSY)})
_TRANSIENT_WINDOWS_ERRORS = frozenset({
    5,   # ERROR_ACCESS_DENIED (often scanners and sync clients)
    32,  # ERROR_SHARING_VIOLATION
    33,  # ERROR_LOCK_VIOLATION
})


def _is_transient(exc: OSError) -> bool:
    return (
        getattr(exc, "winerror", None) in _TRANSIENT_WINDOWS_ERRORS
        or exc.errno in _TRANSIENT_ERRNOS
    )


def replace_with_retry(source: PathLike, destination: PathLike) -> None:
    """Atomically replace `destination`, retrying only transient file locks."""
    delay = INITIAL_RETRY_DELAY_SECONDS
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(safe_entry_path(source), safe_entry_path(destination))
            return
        except OSError as exc:
            if attempt == REPLACE_ATTEMPTS - 1 or not _is_transient(exc):
                raise
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY_SECONDS)


def write_bytes_atomic(path: PathLike, data: bytes) -> Path:
    """Durably publish `data` at `path`. Creates the folder if needed."""
    destination = safe_entry_path(path)
    folder = safe_path(destination.parent)
    folder.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, destination)
    finally:
        safe_entry_path(temporary).unlink(missing_ok=True)
    return destination


def write_text_atomic(path: PathLike, text: str) -> Path:
    return write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: PathLike, payload: Any) -> Path:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return write_text_atomic(path, text)

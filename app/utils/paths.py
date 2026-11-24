"""Safe-path helpers. Every file the app reads or writes goes through these.

Ported from v1 `utils/paths.py`. A path is allowed only when, after symbolic
links and `..` are resolved, it sits under the project folder, the configured
output folder (`XBRL_OUTPUT_DIR`) or the system temp folder.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PathLike = Union[str, os.PathLike]

# macOS has two temp roots (/var/folders/... and /tmp). Resolve once so a
# symbolic link cannot widen the set later.
_TEMP_ROOTS: tuple[Path, ...] = tuple(
    sorted(
        {Path(tempfile.gettempdir()).resolve()}
        | {Path(p).resolve() for p in ("/tmp", "/var/tmp") if Path(p).exists()}
    )
)


class UnsafePathError(PermissionError):
    """A file path outside every approved folder."""


def output_dir() -> Path:
    """The folder that holds the database, uploads and transcripts."""
    configured = os.environ.get("XBRL_OUTPUT_DIR")
    base = Path(configured).expanduser() if configured else PROJECT_ROOT / "output"
    return base.resolve()


def _is_under_safe_root(resolved: Path) -> bool:
    roots = [PROJECT_ROOT, output_dir(), *_TEMP_ROOTS]
    return any(resolved.is_relative_to(root) for root in roots)


def safe_path(path: PathLike) -> Path:
    """Return `path` fully resolved, or raise UnsafePathError if it leaves the
    approved folders."""
    text = os.fspath(path)
    if "\x00" in text:
        raise UnsafePathError("File path contains a null byte.")
    resolved = Path(text).expanduser().resolve()
    if not _is_under_safe_root(resolved):
        raise UnsafePathError(f"File path is outside the approved folders: {resolved}")
    return resolved


def safe_entry_path(path: PathLike) -> Path:
    """`safe_path` for deleting, renaming or replacing. Checks the containing
    folder but keeps the last step as it is, so the operation acts on a
    symbolic link itself and never on the file it points to."""
    candidate = Path(os.fspath(path)).expanduser()
    if candidate.name in ("", ".", ".."):
        raise UnsafePathError(f"File path has no file name: {path!r}")
    return safe_path(candidate.parent) / candidate.name


def safe_segment(value: str) -> str:
    """Return `value` if it is one safe path segment (no separators, no `..`),
    else raise ValueError. For ids joined onto a folder."""
    if (
        not isinstance(value, str)
        or value in ("", ".", "..")
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or value != Path(value).name
    ):
        raise ValueError(f"Not a safe file name: {value!r}")
    return value


def operator_path(path: PathLike) -> Path:
    """Resolve a path the person running a command-line tool typed (copied from
    v1). There is no folder limit: they already have this machine's access, and
    pointing the tool at their own file is its job. Never use this for web
    request data."""
    text = os.fspath(path)
    if "\x00" in text:
        raise UnsafePathError("File path contains a null byte.")
    return Path(text).expanduser().resolve()

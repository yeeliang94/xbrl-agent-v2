"""The app's version, for the health route, the shell and the traces zip."""
from __future__ import annotations

from typing import Optional

from app.utils.paths import PROJECT_ROOT

VERSION = "0.1.0"


def deployed_commit() -> Optional[str]:
    """The commit `scripts/package.py azure` wrote into the package as `version.txt`, so "what
    is live?" has an answer. None when the app runs from a checkout."""
    try:
        return (PROJECT_ROOT / "version.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def version_text() -> str:
    """The traces zip's `version.txt`: the version, and the deployed commit when there is one."""
    commit = deployed_commit()
    return f"{VERSION}\n{commit}\n" if commit else f"{VERSION}\n"

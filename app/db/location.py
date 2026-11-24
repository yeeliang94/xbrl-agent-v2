"""Where the live database file sits. Ported from v1 `db/location.py`.

On the Mac and the Windows machine it is `<output folder>/xbrl.db`. On Azure
App Service the output folder is on the `/home` network drive, which cannot
hold the locks a live SQLite file needs: on 11 November 2026 two containers
opening one file there stopped v1 from starting. So on Azure the live file sits
on the container's own disk, and `app/db/copies.py` saves copies onto `/home`.
"""
from __future__ import annotations

from pathlib import Path

from app.utils.paths import output_dir
from app.utils.runtime import on_azure

DB_FILENAME = "xbrl.db"
# Fixed, not tempfile.gettempdir(): an SSH shell into the container must find
# the same file as the server. Not v1's /tmp/xbrl-live, so the two never meet.
AZURE_LIVE_DIR = Path("/tmp/xbrl-v2-live")
# Not v1's `db-copies`: v2 runs on v1's App Service, and v1's folder holds v1's
# copies and its own owner.json. Sharing it would stop v1 saving after a rollback.
COPIES_FOLDER = "v2-db-copies"


def live_path() -> Path:
    return AZURE_LIVE_DIR / DB_FILENAME if on_azure() else output_dir() / DB_FILENAME


def copies_dir() -> Path:
    return output_dir() / COPIES_FOLDER

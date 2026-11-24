"""Where the app is running. A fact about the machine, read by the login layer (secure cookies,
the start-up checks, the lockout's address) and the database layer (where the live file sits)."""
from __future__ import annotations

import os


def on_azure() -> bool:
    """True on Azure App Service, which always sets WEBSITE_SITE_NAME."""
    return bool(os.environ.get("WEBSITE_SITE_NAME"))

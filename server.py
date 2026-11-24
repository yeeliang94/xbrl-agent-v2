"""The app for Azure App Service. Its startup command, set in the portal for v1, is

    uvicorn server:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"

v2 keeps that command: this file hands it v2's app. The login lockout does not rely on
`--proxy-headers`, whose address the sender can write; it reads the one Azure's front end
adds (`app/auth/routes.py`). Run one process only (no `--workers`): the job worker, the lockout and the
database copies assume one. Locally, start with `start.sh` or `start.bat` instead.
"""
from app.main import app  # noqa: F401

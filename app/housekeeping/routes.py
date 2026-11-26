"""Admin housekeeping on the Settings page (`docs/api-contract.md`, "Housekeeping"): the connection test.
There is no automatic clean-up: runs are removed by hand (owner, 26 November 2026)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.deps import require_admin
from app.auth.store import User
from app.models import connection
from app.settings import store as settings

router = APIRouter(prefix="/api/admin")


@router.post("/connection-test")
async def connection_test(admin: User = Depends(require_admin)):
    """One tiny call to each model the app is set to use. The key and the address stay in `.env`."""
    models = settings.read()["models"]
    return {"results": await connection.check_models([models[role] for role in settings.ROLES])}

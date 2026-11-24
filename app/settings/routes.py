"""`GET /api/settings`, `PUT /api/settings` (admin) and `GET /api/models`."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.auth.deps import current_user, require_admin
from app.auth.store import User
from app.models import catalog
from app.settings import store

router = APIRouter(prefix="/api")


@router.get("/settings")
def get_settings(user: User = Depends(current_user)):
    return store.read()


@router.put("/settings")
def put_settings(changes: dict[str, Any] = Body(...), admin: User = Depends(require_admin)):
    try:
        return store.update(changes, admin.email)
    except store.SettingsError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.get("/models")
async def get_models(user: User = Depends(current_user)):
    return {"models": await catalog.list_models()}

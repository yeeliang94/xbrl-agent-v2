"""The FastAPI app: `/api/*` routes, the job worker and the built browser app.

Start it with `venv/bin/python -m app.main` (port 8100, or PORT from `.env`). On Azure the
App Service's startup command runs `uvicorn server:app` (see `server.py`).
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app import db
from app.db import copies, location
from app.auth import admin_routes, middleware, routes as auth_routes, startup as auth_startup
from app.catalog import loader as catalogue
from app.documents import routes as documents_routes
from app.figures import routes as figures_routes
from app.filing import routes as filing_routes
from app.filing.investigate import routes as placement_routes
from app.guidance import routes as guidance_routes
from app.jobs import queue, worker
from app.models import factory
from app.notes import routes as notes_routes
from app.reading import routes as reading_routes
from app.review import rounds as review_rounds, routes as review_routes
from app.records import routes as records_routes, server_log
from app.runs import routes as runs_routes
from app.scope import routes as scope_routes
from app.scoring import routes as scoring_routes
from app.settings import routes as settings_routes
from app.utils.paths import PROJECT_ROOT, safe_path
from app.utils.runtime import on_azure
from app.utils.version import VERSION, deployed_commit as _deployed_commit

load_dotenv(PROJECT_ROOT / ".env")  # a real environment variable wins over .env
factory.ensure_certificate_trust()

logger = logging.getLogger(__name__)

WEB_DIST = PROJECT_ROOT / "web" / "dist"


def create_app(*, start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server_log.setup_logging()   # daily files under the output folder, and the console
        if on_azure():   # before anything opens the database
            outcome = copies.restore(location.live_path(), location.copies_dir())
            logger.info("Database copies: %s.", outcome)
        db.init_db()
        await asyncio.to_thread(catalogue.load_catalogue)  # quick when the templates have not changed
        status = auth_startup.bootstrap_admin_from_env()
        if status in ("created", "promoted-existing"):
            logger.info("Bootstrap admin: %s", status)
        auth_startup.check_production_config()
        auth_startup.ensure_dev_user()
        failed_rounds = review_rounds.recover_after_restart()   # before the queue hands their jobs back
        if failed_rounds:
            logger.info("Marked %d correction round(s) left working as failed.", failed_rounds)
        recovered = queue.recover_after_restart()
        if recovered:
            logger.info("Marked %d interrupted job(s) for retry.", recovered)
        if on_azure():   # last: a start that failed never takes saving away
            copies.start_saving(location.live_path(), location.copies_dir())
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run_forever(stop)) if start_worker else None
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await asyncio.to_thread(copies.stop)   # one last copy, once the jobs have stopped

    app = FastAPI(title="XBRL Agent v2", version=VERSION, lifespan=lifespan)
    app.middleware("http")(middleware.auth_middleware)
    app.middleware("http")(server_log.run_context)

    @app.get("/api/health")
    def health():
        body = {"status": "ok", "version": VERSION, "commit": _deployed_commit()}
        if (saved := copies.status()) is not None:
            body["database_copy"] = saved
        return body

    app.include_router(auth_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(runs_routes.router)
    app.include_router(__import__("app.runs.control_routes", fromlist=["router"]).router)   # redo, cost
    app.include_router(documents_routes.router)
    app.include_router(reading_routes.router)
    app.include_router(figures_routes.router)
    app.include_router(notes_routes.router)
    app.include_router(review_routes.router)
    app.include_router(scope_routes.router)
    app.include_router(guidance_routes.router)
    app.include_router(scoring_routes.router)
    app.include_router(placement_routes.router)
    app.include_router(filing_routes.router)
    app.include_router(records_routes.router)
    app.include_router(__import__("app.reports.routes", fromlist=["router"]).router)   # step 10
    app.include_router(__import__("app.starting.routes", fromlist=["router"]).router)   # step 10d
    app.include_router(__import__("app.issues.routes", fromlist=["router"]).router)   # go-live A2
    app.include_router(__import__("app.housekeeping.routes", fromlist=["router"]).router)   # go-live A7: connection test

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(rest: str):
        return JSONResponse(status_code=404, content={"detail": "There is no such address."})

    @app.get("/{rest:path}", include_in_schema=False)
    def browser_app(rest: str):
        return _serve_browser_app(rest)

    return app


def _serve_browser_app(rest: str):
    """A file from `web/dist` when it exists, else `index.html` (single-page
    fallback). A plain message when the browser app has not been built."""
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return PlainTextResponse(
            "The browser app has not been built yet. Run `npm run build` in web/.",
        )
    if rest:
        try:
            candidate = safe_path(WEB_DIST / rest)
        except PermissionError:
            candidate = None
        if candidate is not None and candidate.is_relative_to(WEB_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(index)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8100")))

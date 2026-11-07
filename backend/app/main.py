from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import sessionmaker

from . import models  # noqa: F401  (registers the tables on Base.metadata)
from .config import Settings
from .db import Base, make_engine
from .errors import ServiceError
from .ratelimit import RateLimiter
from .routers import clients, health, onboardings, portal, templates
from .storage import Storage

log = logging.getLogger("uvicorn.error")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    for w in settings.optional_warnings():
        log.warning(w)
    engine = make_engine(settings.database_url)
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)  # local convenience. Postgres uses Alembic migrations.

    # Interactive API docs are for local work only: they are unauthenticated.
    local = settings.app_env == "local"
    app = FastAPI(
        title="Voicent Onboarding", version="0.1.0",
        docs_url="/api/swagger" if local else None, redoc_url=None, openapi_url="/api/openapi.json" if local else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(engine, expire_on_commit=False)
    app.state.storage = Storage(settings) if settings.uploads_enabled else None
    app.state.limit_exchange_ip = RateLimiter(settings.rate_exchange_per_ip)
    app.state.limit_exchange_all = RateLimiter(settings.rate_exchange_global)
    app.state.limit_writes = RateLimiter(settings.rate_writes_per_link)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    for r in (health.router, clients.router, templates.router, onboardings.router, portal.router):
        app.include_router(r, prefix="/api")
    _serve_frontend(app, settings.static_dir)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError):
        body = {"detail": exc.message}
        if exc.problems:
            body["problems"] = exc.problems
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(LookupError)
    async def _lookup(_: Request, exc: LookupError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    return app


def _serve_frontend(app: FastAPI, static_dir: str) -> None:
    """In the container one service serves the built SPA next to /api. No-op when there is no build."""
    root = Path(static_dir).resolve() if static_dir else None
    if not root or not (root / "index.html").is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        return FileResponse(root / "index.html")  # client-side routes (/c/:token, /clients) land on the app

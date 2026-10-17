"""Application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.deps import require_admin
from app.errors import install_error_handlers
from app.middleware import BodyGuardMiddleware
from app.ratelimit import LoginLimiter, RequestLimiter
from app.routers import admin, auth, dashboard, ha, ingest, preferences, public
from app.scheduler import build_scheduler
from app.services import maintenance
from app.spa import install_spa
from app.version import VERSION


class SecurityHeadersMiddleware:
    """nosniff + no-store on everything: responses may carry health data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)


async def _ensure_heart_points(app: FastAPI) -> None:
    """Background: compute the Heart Points of the days that lack them (never blocks the start)."""
    try:
        async with app.state.sessionmaker() as session:
            await maintenance.recompute_heart_points(session, app.state.settings, only_missing=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.getLogger("sbh.heartpoints").exception("startup heart points failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.sqlalchemy_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = build_scheduler(app) if settings.enable_scheduler else None
        startup: asyncio.Task[None] | None = None
        if scheduler:
            scheduler.start()
            # first deploy / changed HRmax settings: compute the missing Heart Points in background
            startup = asyncio.create_task(_ensure_heart_points(app))
        try:
            yield
        finally:
            if startup is not None:
                startup.cancel()
            if scheduler:
                scheduler.shutdown(wait=False)
            await engine.dispose()

    app = FastAPI(
        title="StatisticsByHeart Writer",
        version=VERSION,
        description="Ingest API (contract v1: docs/api-contract.md) and admin endpoints.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.login_limiter = LoginLimiter(
        settings.login_max_failures, settings.login_window_seconds
    )
    app.state.ha_limiter = RequestLimiter(settings.ha_rate_limit_per_minute)

    install_error_handlers(app)
    app.add_middleware(BodyGuardMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(public.router)
    app.include_router(ingest.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(dashboard.router)
    app.include_router(preferences.router)
    app.include_router(ha.router)

    if settings.enable_docs:
        _install_docs(app)
    install_spa(app, settings.static_dir)  # last: its catch-all route must not shadow the API
    return app


def _install_docs(app: FastAPI) -> None:
    """OpenAPI JSON for logged-in admins only (no public schema, no external CDN assets)."""

    @app.get("/api/openapi.json", include_in_schema=False, dependencies=[Depends(require_admin)])
    async def openapi_json() -> dict[str, Any]:
        return app.openapi()

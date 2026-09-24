"""Application factory.

``uvicorn app.main:app`` serves the module-level ``app``; tests call ``create_app()``
with their own settings.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.ai.providers import build_provider
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import install_metrics
from app.core.rate_limit import RateLimiter
from app.core.request_context import RequestContextMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import dispose_engine
from app.realtime.broker import Broker
from app.routers import (
    ai,
    attachments,
    auth,
    comments,
    dashboard,
    events,
    health,
    incidents,
    notifications,
    teams,
    users,
)
from app.routers import settings as admin_settings
from app.services.ai_service import DailyBudget
from app.storage import build_storage

log = get_logger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    _init_sentry(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("startup", version=__version__, git_sha=settings.git_sha, env=settings.app_env)
        if settings.is_production and settings.allow_self_register:
            log.warning("self_registration_enabled_in_production")
        worker_task = None
        if settings.run_worker_in_api:
            # Single-service hosts: run the notification worker inside the API process.
            from app.notifications.worker import Worker

            worker = Worker(settings)
            worker_task = asyncio.create_task(worker.run(), name="notification-worker")
        yield
        if worker_task:
            worker.stop()
            await worker_task
        await app.state.broker.close()
        await dispose_engine()
        log.info("shutdown")

    app = FastAPI(
        title="Tasky API",
        version=__version__,
        description="AI-assisted incident management. All business routes live under /api/v1.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # The settings this app was built with are the ones its routes see. (async, so
    # FastAPI does not hop to a worker thread to resolve it on every request)
    async def _settings() -> Settings:
        return settings

    app.dependency_overrides[get_settings] = _settings

    app.state.rate_limiter = RateLimiter()
    app.state.broker = Broker(settings.database_url)
    app.state.storage = build_storage(settings)
    app.state.llm = build_provider(settings)
    app.state.ai_budget = DailyBudget()

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(users.avatars)
    app.include_router(teams.router)
    app.include_router(incidents.router)
    app.include_router(comments.router)
    app.include_router(dashboard.router)
    app.include_router(notifications.router)
    app.include_router(notifications.admin)
    app.include_router(admin_settings.router)
    app.include_router(attachments.router)
    app.include_router(ai.router)
    app.include_router(events.router)

    if settings.metrics_enabled:
        # Exposed on the container port only; Caddy refuses /metrics from the internet.
        install_metrics(app, excluded=frozenset({"/health", "/api/v1/health", "/metrics"}))

    # add_middleware() prepends, so the last one added is outermost. Order (outside-in):
    # request context -> security headers -> CORS -> metrics -> routing.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)

    return app


def _init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release=f"incident-desk-api@{__version__}+{settings.git_sha}",
        traces_sample_rate=0.0,
        send_default_pii=False,
    )


app = create_app()

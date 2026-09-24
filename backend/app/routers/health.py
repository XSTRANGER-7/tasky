"""Liveness/readiness probe used by Docker, Caddy, CI and the uptime monitor.

Returns 200 only when the database answers, 503 otherwise, so a host never routes
traffic to an instance that cannot serve it. Served at ``/health`` (hosts, Docker) and
``/api/v1/health`` (reachable through the Vercel ``/api/*`` rewrite).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker, ping_database
from app.schemas.notification import WorkerStatus
from app.services.worker_status import worker_status

DB_TIMEOUT_SECONDS = 2.0

log = get_logger(__name__)
router = APIRouter(tags=["health"])

DbCheck = Callable[[], Awaitable[None]]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "unreachable"]
    version: str
    git_sha: str
    env: str
    worker: WorkerStatus | None = None  # informational; never fails the probe


WorkerProbe = Callable[[Settings], Awaitable[WorkerStatus | None]]


async def _probe_worker(settings: Settings) -> WorkerStatus | None:
    async with get_sessionmaker()() as session:
        return await worker_status(session, settings)


async def get_worker_probe() -> WorkerProbe:
    return _probe_worker


async def get_db_check() -> DbCheck:
    return ping_database


async def _health(
    response: Response,
    settings: Settings = Depends(get_settings),
    db_check: DbCheck = Depends(get_db_check),
    worker_probe: WorkerProbe = Depends(get_worker_probe),
) -> HealthResponse:
    try:
        await asyncio.wait_for(db_check(), timeout=DB_TIMEOUT_SECONDS)
        db_state: Literal["ok", "unreachable"] = "ok"
    except Exception as exc:  # any failure (timeout, auth, DNS) means "not ready"
        log.warning("health_db_unreachable", error=type(exc).__name__, detail=str(exc)[:200])
        db_state = "unreachable"

    healthy = db_state == "ok"
    worker: WorkerStatus | None = None
    if healthy:
        try:
            worker = await asyncio.wait_for(worker_probe(settings), timeout=DB_TIMEOUT_SECONDS)
        except Exception as exc:  # the worker table is informational only
            log.warning("health_worker_probe_failed", error=type(exc).__name__)
    response.status_code = 200 if healthy else 503
    response.headers["Cache-Control"] = "no-store"
    return HealthResponse(
        status="ok" if healthy else "degraded",
        db=db_state,
        version=__version__,
        git_sha=settings.git_sha,
        env=settings.app_env,
        worker=worker,
    )


router.add_api_route(
    "/health",
    _health,
    methods=["GET"],
    response_model=HealthResponse,
    summary="Health check",
    responses={503: {"model": HealthResponse, "description": "Database unreachable"}},
)
router.add_api_route(
    "/api/v1/health",
    _health,
    methods=["GET"],
    response_model=HealthResponse,
    include_in_schema=False,
)

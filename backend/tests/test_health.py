from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import __version__
from app.core.config import Settings
from app.db.session import dispose_engine
from app.notifications.worker import Worker
from app.routers import health
from tests.fakes import FakeSender


def _override_db(app: FastAPI, check: health.DbCheck) -> None:
    async def provide() -> health.DbCheck:
        return check

    async def no_worker(_: object) -> None:
        return None

    async def provide_probe() -> health.WorkerProbe:
        return no_worker

    app.dependency_overrides[health.get_db_check] = provide
    app.dependency_overrides[health.get_worker_probe] = provide_probe


async def _ok() -> None:
    return None


async def _down() -> None:
    raise ConnectionRefusedError("connection refused")


async def test_health_ok_when_db_answers(app: FastAPI, client: httpx.AsyncClient) -> None:
    _override_db(app, _ok)

    res = await client.get("/health")

    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "db": "ok",
        "version": __version__,
        "git_sha": "testsha",
        "env": "test",
        "worker": None,
    }
    assert res.headers["cache-control"] == "no-store"


async def test_health_503_when_db_down(app: FastAPI, client: httpx.AsyncClient) -> None:
    _override_db(app, _down)

    res = await client.get("/health")

    assert res.status_code == 503
    assert res.json()["status"] == "degraded"
    assert res.json()["db"] == "unreachable"


async def test_health_503_when_db_hangs(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "DB_TIMEOUT_SECONDS", 0.05)

    async def _hang() -> None:
        await asyncio.sleep(5)

    _override_db(app, _hang)

    res = await client.get("/health")

    assert res.status_code == 503
    assert res.json()["db"] == "unreachable"


async def test_health_alias_under_api_prefix(app: FastAPI, client: httpx.AsyncClient) -> None:
    """The SPA reaches the API only through the Vercel /api/* rewrite."""
    _override_db(app, _ok)

    res = await client.get("/api/v1/health")

    assert res.status_code == 200
    assert res.json()["status"] == "ok"


async def test_openapi_documents_health(client: httpx.AsyncClient) -> None:
    res = await client.get("/openapi.json")

    assert res.status_code == 200
    paths = res.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/health" not in paths


async def test_metrics_label_route_templates_and_skip_probes(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.get("/_test/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    _override_db(app, _ok)
    await client.get("/_test/items/1")
    await client.get("/_test/items/2")
    await client.get("/health")

    res = await client.get("/metrics")

    assert res.status_code == 200
    # One series per route template, not per concrete URL (bounded cardinality).
    assert (
        'http_requests_total{handler="/_test/items/{item_id}",method="GET",status="200"} 2.0'
        in res.text
    )
    assert "/_test/items/1" not in res.text
    assert 'handler="/health"' not in res.text


@pytest.mark.db
async def test_health_against_real_database(client: httpx.AsyncClient) -> None:
    try:
        res = await client.get("/health")
    finally:
        await dispose_engine()  # the pool is bound to this test's event loop

    assert res.status_code == 200, res.text
    assert res.json()["db"] == "ok"


@pytest.mark.db
async def test_health_reports_worker_heartbeat(
    client: httpx.AsyncClient, settings: Settings, db: async_sessionmaker[AsyncSession]
) -> None:
    try:
        before = (await client.get("/health")).json()["worker"]
        await Worker(settings, sender=FakeSender(), sessionmaker=db).heartbeat()
        after = (await client.get("/health")).json()["worker"]
    finally:
        await dispose_engine()  # /health used the app's own pool on this event loop

    assert before["status"] == "unknown"
    assert after["status"] == "ok"
    assert after["seconds_since_beat"] < 5

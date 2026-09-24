"""Live updates: NOTIFY only on commit, fan-out through the broker, and the SSE endpoint."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import dispose_engine
from app.realtime import publish
from app.realtime.broker import Broker
from tests.conftest import TEST_DATABASE_URL, CreateIncident, Person

pytestmark = pytest.mark.db
Db = async_sessionmaker[AsyncSession]


@pytest.fixture
async def broker() -> AsyncIterator[Broker]:
    b = Broker(TEST_DATABASE_URL)
    yield b
    await b.close()


async def _next(queue: asyncio.Queue[dict[str, Any]], wait: float = 3) -> dict[str, Any]:
    return await asyncio.wait_for(queue.get(), wait)


async def test_messages_are_published_on_commit_only(broker: Broker, db: Db) -> None:
    queue = await broker.subscribe()

    async with db() as s:
        publish.queue(s, {"type": "incident.updated", "incident": "TASK-1"})
        await s.execute(text("SELECT 1"))
        await s.rollback()
    async with db() as s:
        publish.queue(s, {"type": "incident.updated", "incident": "TASK-2"})
        publish.queue(s, {"type": "incident.updated", "incident": "TASK-2"})  # de-duplicated
        await s.commit()

    assert await _next(queue) == {"type": "incident.updated", "incident": "TASK-2"}
    with pytest.raises(TimeoutError):
        await _next(queue, wait=0.5)  # neither the rolled-back one nor a duplicate


async def test_api_changes_reach_subscribers(
    broker: Broker, app: FastAPI, create_incident: CreateIncident, people: dict[str, Person]
) -> None:
    queue = await broker.subscribe()

    inc = await create_incident(assignee_id=str(people["max"].id))

    # created + updated (the assignment) + the assignee's notification
    received = [await _next(queue) for _ in range(3)]
    created = {"type": "incident.created", "incident": inc["key"], "team": inc["team_id"]}
    assert created in received
    assert {
        "type": "notification.new",
        "user": str(people["max"].id),
        "incident": inc["key"],
    } in received


async def test_sse_stream_requires_auth(client: httpx.AsyncClient, db: object) -> None:
    assert (await client.get("/api/v1/events/stream")).status_code == 401
    bad = await client.get("/api/v1/events/stream", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


@pytest.fixture
async def live_server(app: FastAPI) -> AsyncIterator[str]:
    """The app on a real local port. httpx's in-process ASGI transport buffers whole
    responses, so a never-ending SSE stream can only be tested over real HTTP."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_config=None)
    )
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await app.state.broker.close()
        await asyncio.wait_for(task, timeout=5)
        await dispose_engine()


async def test_sse_stream_delivers_events_and_filters_other_peoples_notifications(
    live_server: str, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    ready = asyncio.Event()

    async def read_stream() -> None:
        async with (
            httpx.AsyncClient(base_url=live_server, timeout=10) as http,
            http.stream("GET", "/api/v1/events/stream", headers=people["mira"].headers) as res,
        ):
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            assert res.headers["cache-control"] == "no-cache"
            event = None
            async for line in res.aiter_lines():
                if line.startswith("event: "):
                    event = line.removeprefix("event: ")
                elif line.startswith("data: ") and event:
                    events.append((event, json.loads(line.removeprefix("data: "))))
                    if event == "ready":
                        ready.set()
                    if event == "incident.created":
                        return

    reader = asyncio.create_task(read_stream())
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
        inc = await create_incident(by="max", assignee_id=str(people["admin"].id))
        await asyncio.wait_for(reader, timeout=5)
    finally:
        reader.cancel()

    kinds = [e for e, _ in events]
    assert kinds[0] == "ready"
    created = {"type": "incident.created", "incident": inc["key"], "team": inc["team_id"]}
    assert ("incident.created", created) in events
    assert "notification.new" not in kinds  # that one was for the admin, not Mira

"""Fan-out of Postgres NOTIFY messages to SSE subscribers in this process.

One dedicated connection per API process LISTENs on the channel; every browser tab gets
a bounded queue. Because the source is Postgres, messages published by any API process
or the worker reach every subscriber, and only committed changes are ever published.
A slow client loses messages (its queue is bounded) instead of stalling everyone; the
client refetches on reconnect anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import psycopg

from app.core.logging import get_logger
from app.realtime.publish import CHANNEL

log = get_logger(__name__)

QUEUE_SIZE = 100


def _conninfo(database_url: str) -> str:
    """SQLAlchemy URL -> libpq URL (drop the ``+psycopg`` driver suffix)."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class Broker:
    def __init__(self, database_url: str) -> None:
        self._conninfo = _conninfo(database_url)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._ready.clear()
            self._task = asyncio.create_task(self._listen(), name="realtime-listener")
        # Wait (briefly) until LISTEN is active so nothing published right after the
        # client connects is missed.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ready.wait(), timeout=5)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _fan_out(self, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("sse_queue_full_dropping")

    async def _listen(self) -> None:
        delay = 1.0
        while self._subscribers:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self._ready.set()
                    delay = 1.0
                    log.info("realtime_listening", channel=CHANNEL)
                    async for notify in conn.notifies():
                        try:
                            self._fan_out(json.loads(notify.payload))
                        except json.JSONDecodeError:
                            log.warning("realtime_bad_payload")
                        if not self._subscribers:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("realtime_listener_error", error=str(exc)[:200], retry_in=delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
        self._ready.clear()

    async def close(self) -> None:
        self._subscribers.clear()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

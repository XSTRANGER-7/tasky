"""GET /api/v1/events/stream -- Server-Sent Events for live list/detail/notification updates.

* Auth: ``Authorization: Bearer`` (the SPA uses fetch-event-source so it can send headers).
  The token is checked once with a short-lived DB session, so a long-lived stream never
  pins a pooled connection. The stream ends when the access token expires; the client
  reconnects with a fresh one.
* Events: ``incident.created``, ``incident.updated`` (only to members of the incident's
  team) and ``notification.new`` (only to its recipient). Team membership is re-read
  every 30 s, so someone who joins or leaves a team starts or stops seeing its events
  without reconnecting. A comment line is sent every 15 s so proxies keep the
  connection open.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.deps import AppSettings, Credentials
from app.core.errors import Unauthenticated
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.realtime.broker import Broker
from app.repositories import team_repo
from app.services import auth_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/events", tags=["events"])

KEEPALIVE_SECONDS = 15.0
TEAMS_REFRESH_SECONDS = 30.0


def _format(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _expires_at(token: str) -> float:
    claims = jwt.decode(token, options={"verify_signature": False})  # already verified
    return float(claims["exp"])


@router.get(
    "/stream",
    summary="Live updates (Server-Sent Events)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream(
    request: Request, settings: AppSettings, credentials: Credentials
) -> StreamingResponse:
    if credentials is None:
        raise Unauthenticated()
    async with get_sessionmaker()() as session:
        user = await auth_service.authenticate(session, settings, credentials.credentials)
        teams = {str(t) for t in await team_repo.team_ids_of_user(session, user.id)}
    user_id = str(user.id)
    expires_at = _expires_at(credentials.credentials)
    broker: Broker = request.app.state.broker

    async def refresh_teams() -> set[str]:
        async with get_sessionmaker()() as session:
            return {str(t) for t in await team_repo.team_ids_of_user(session, user.id)}

    async def events() -> AsyncIterator[str]:
        nonlocal teams
        teams_read_at = time.monotonic()
        queue = await broker.subscribe()
        log.info("sse_connected", user_id=user_id, subscribers=broker.subscriber_count)
        try:
            yield "retry: 5000\n\n"
            yield _format("ready", {"user": user_id})
            while True:
                remaining = expires_at - time.time()
                if remaining <= 0:
                    yield _format("reauth", {"reason": "token_expired"})
                    return
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=min(KEEPALIVE_SECONDS, remaining)
                    )
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keep-alive\n\n"
                    continue
                kind = str(message.get("type", ""))
                if kind == "notification.new" and message.get("user") != user_id:
                    continue  # someone else's notification
                team = message.get("team")
                if team is not None:
                    if time.monotonic() - teams_read_at > TEAMS_REFRESH_SECONDS:
                        teams, teams_read_at = await refresh_teams(), time.monotonic()
                    if team not in teams:
                        continue  # another team's incident
                yield _format(kind, {k: v for k, v in message.items() if k != "user"})
        finally:
            broker.unsubscribe(queue)
            log.info("sse_disconnected", user_id=user_id, subscribers=broker.subscriber_count)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

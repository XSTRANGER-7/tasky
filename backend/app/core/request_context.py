"""Request ID + access-log middleware.

Pure ASGI (not ``BaseHTTPMiddleware``) so it adds no buffering and stays correct for the
long-lived SSE stream added in Phase 4.

* Reuses an inbound ``X-Request-ID`` when it is well-formed, otherwise mints
  ``req_<ULID>``; the ID is echoed on every response.
* Binds ``request_id`` into the structlog context so every log line of the request
  carries it, and exposes it via :func:`current_request_id` for error envelopes.
* Is the last line of defence for unhandled exceptions: it logs the traceback and returns
  the standard 500 envelope *with* the request id. (Starlette would otherwise handle
  them in ``ServerErrorMiddleware``, outside this middleware, where the id is gone.)
* Emits exactly one access-log line per request with route, status and duration.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextvars import ContextVar

import sentry_sdk
import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

REQUEST_ID_HEADER = "x-request-id"
_INBOUND_ID = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_QUIET_PATHS = frozenset({"/health", "/api/v1/health", "/metrics"})

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
log = get_logger("app.access")


def new_ulid() -> str:
    """26-char Crockford ULID: 48-bit ms timestamp + 80 random bits (sortable by time)."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> shift) & 0x1F] for shift in range(125, -1, -5))


def new_request_id() -> str:
    return f"req_{new_ulid()}"


def current_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = _header(scope, REQUEST_ID_HEADER)
        request_id = inbound if inbound and _INBOUND_ID.match(inbound) else new_request_id()
        token = _request_id.set(request_id)
        log_tokens = structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        response_started = False
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            log.exception("unhandled_exception", exc_type=type(exc).__name__)
            sentry_sdk.capture_exception(exc)
            if response_started:  # headers already sent; nothing sensible left to do
                raise
            await _send_internal_error(send_with_id, request_id)
        finally:
            path = scope.get("path", "")
            if path not in _QUIET_PATHS or status_code >= 400:
                route = scope.get("route")
                log.info(
                    "http_request",
                    method=scope.get("method"),
                    path=path,
                    route=getattr(route, "path", None),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    client_ip=(scope.get("client") or (None,))[0],
                )
            structlog.contextvars.reset_contextvars(**log_tokens)
            _request_id.reset(token)


async def _send_internal_error(send: Send, request_id: str) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
                "details": {},
                "request_id": request_id,
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _header(scope: Scope, name: str) -> str | None:
    target = name.encode()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return str(value.decode("latin-1"))
    return None

# ADR 0002 - Cross-cutting middleware is pure ASGI

- Status: accepted
- Date: 2026-09-22

## Context

The API needs request IDs, access logging, security headers and a guaranteed error
envelope on every response. Starlette offers `BaseHTTPMiddleware` (convenient,
request/response objects) or raw ASGI middleware.

`BaseHTTPMiddleware` wraps the response body in its own stream, which has a history of
problems with streaming responses and background tasks -- and Phase 4 adds a long-lived
Server-Sent Events stream. Separately, Starlette dispatches handlers registered for the
bare `Exception` class from `ServerErrorMiddleware`, the outermost layer, i.e. *after*
our middleware has returned and its context (the request ID) is gone.

## Decision

- `RequestContextMiddleware` and `SecurityHeadersMiddleware` are pure ASGI classes that
  only observe/modify `http.response.start` messages.
- `RequestContextMiddleware` is the outermost user middleware and is also the last line
  of defence for unhandled exceptions: it logs the traceback, reports it to Sentry and
  emits the standard 500 envelope including the request ID.
- Domain and framework errors (4xx) keep using FastAPI exception handlers
  (`app/core/errors.py`).

## Consequences

- SSE and any other streaming response pass through without buffering.
- Every response, including crashes, carries `X-Request-ID`, and the same ID appears in
  the log line, the error body and Sentry.
- Slightly more low-level code (ASGI messages instead of Request/Response), covered by
  `tests/test_request_context.py`.

"""Prometheus HTTP metrics as a pure-ASGI middleware.

Replaces prometheus-fastapi-instrumentator, which walks the router tree itself and broke
on FastAPI's included-router objects. Here the label comes from ``scope["route"]``,
which routing fills in with the matched route *template* (``/api/v1/incidents/{id}``),
so cardinality stays bounded: unmatched paths are all labelled ``<unmatched>``.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram
from prometheus_client.exposition import generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED = "<unmatched>"
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class HttpMetrics:
    """The metric families for one app, registered in their own registry."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry
        self.requests = Counter(
            "http_requests_total",
            "HTTP requests by method, route template and status code.",
            ["method", "handler", "status"],
            registry=registry,
        )
        self.latency = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency by method and route template.",
            ["method", "handler"],
            buckets=_BUCKETS,
            registry=registry,
        )


class MetricsMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: HttpMetrics, excluded: frozenset[str]) -> None:
        self.app = app
        self.metrics = metrics
        self.excluded = excluded

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.excluded:
            await self.app(scope, receive, send)
            return

        status = 500
        started = time.perf_counter()

        async def send_capturing_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_capturing_status)
        finally:
            route = scope.get("route")
            handler = getattr(route, "path", None) or UNMATCHED
            method = scope.get("method", "")
            self.metrics.requests.labels(method, handler, str(status)).inc()
            self.metrics.latency.labels(method, handler).observe(time.perf_counter() - started)


def install_metrics(app: FastAPI, *, excluded: frozenset[str]) -> None:
    """Add the middleware and the ``/metrics`` endpoint. A registry per app keeps
    ``create_app()`` re-entrant (tests build several apps in one process)."""
    metrics = HttpMetrics(CollectorRegistry())
    app.add_middleware(MetricsMiddleware, metrics=metrics, excluded=excluded)

    async def metrics_endpoint() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

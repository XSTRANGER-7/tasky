"""Fixed-window rate limiting as a FastAPI dependency.

In-memory and per process: enough to blunt credential stuffing on a single small
instance (the spec's login 5/min, register 3/min per IP). With N uvicorn workers the
effective limit is N x the configured one; the ``RateLimiter`` interface is the seam
for a Redis-backed store if that ever matters.

Responses carry the IETF draft ``RateLimit-Limit / -Remaining / -Reset`` headers, and a
429 carries ``Retry-After``.
"""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import Depends, Request, Response

from app.core.config import Settings, get_settings
from app.core.errors import RateLimited

_MAX_KEYS = 50_000  # memory bound: stale windows are pruned beyond this


@dataclass
class _Window:
    started: float
    count: int


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._windows: dict[str, _Window] = {}
        self._lock = Lock()

    def hit(self, key: str, limit: int, period: float) -> tuple[bool, int, float]:
        """Count one request. Returns (allowed, remaining, seconds_until_reset)."""
        now = self._clock()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.started >= period:
                window = _Window(started=now, count=0)
                self._windows[key] = window
                if len(self._windows) > _MAX_KEYS:
                    self._prune(now, period)
            window.count += 1
            reset = max(0.0, period - (now - window.started))
            return window.count <= limit, max(0, limit - window.count), reset

    def _prune(self, now: float, period: float) -> None:
        for key in [k for k, w in self._windows.items() if now - w.started >= period]:
            del self._windows[key]


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers (with FORWARDED_ALLOW_IPS) already resolved X-Forwarded-For.
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str, limit_of: Callable[[Settings], int], period: float = 60.0
) -> Callable[..., Awaitable[None]]:
    """Dependency factory, e.g. ``rate_limit("login", lambda s: s.login_rate_limit_per_min)``."""

    async def dependency(
        request: Request, response: Response, settings: Settings = Depends(get_settings)
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        limiter: RateLimiter = request.app.state.rate_limiter
        limit = limit_of(settings)
        allowed, remaining, reset = limiter.hit(f"{scope}:{client_ip(request)}", limit, period)
        headers = {
            "RateLimit-Limit": str(limit),
            "RateLimit-Remaining": str(remaining),
            "RateLimit-Reset": str(math.ceil(reset)),
        }
        if not allowed:
            raise RateLimited(
                "Too many requests, try again shortly",
                details={"retry_after_seconds": math.ceil(reset)},
                headers={**headers, "Retry-After": str(math.ceil(reset))},
            )
        response.headers.update(headers)

    return dependency

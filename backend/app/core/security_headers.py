"""Baseline security headers on every API response (spec section 13)."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The API only serves JSON; Swagger/ReDoc at /docs and /redoc load their assets from
# jsDelivr, so those two paths get a slightly wider policy.
_API_CSP = b"default-src 'none'; frame-ancestors 'none'"
_DOCS_CSP = (
    b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    b"font-src 'self' https://fonts.gstatic.com; "
    b"img-src 'self' data: https://fastapi.tiangolo.com; "
    b"worker-src blob:; frame-ancestors 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        csp = _DOCS_CSP if scope.get("path", "").startswith(_DOCS_PATHS) else _API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                # A route may set a stricter policy of its own (e.g. sandboxed file downloads).
                headers += [
                    (name, value)
                    for name, value in (
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"x-frame-options", b"DENY"),
                        (b"content-security-policy", csp),
                    )
                    if name not in present
                ]
                if self.hsts:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)

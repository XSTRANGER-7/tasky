"""One error envelope for every failure.

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "req_..."}}

Phase 0 wires the envelope for framework errors (404/405/422; the 500 fallback lives in
``request_context`` so it can carry the request id). Phase 1 adds the domain exceptions
(``InvalidTransition`` -> 409, ``PermissionDenied`` -> 403, ...) as subclasses of
:class:`AppError`, so routers never build error responses by hand.
"""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id


class AppError(Exception):
    """Base for expected, client-visible errors raised by the service layer."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}
        self.headers = dict(headers or {})


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"

    def __init__(self, message: str = "Authentication required", **kwargs: Any) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class PermissionDenied(AppError):
    status_code = 403
    code = "forbidden"

    def __init__(
        self, message: str = "You do not have permission to do this", **kwargs: Any
    ) -> None:
        super().__init__(message, **kwargs)


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class InvalidInput(AppError):
    status_code = 422
    code = "validation_error"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": current_request_id(),
        }
    }
    return JSONResponse(jsonable_encoder(body), status_code=status_code, headers=headers)


def _code_for(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered for AppError only
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, _code_for(exc.status_code), message, headers=exc.headers)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    fields = [
        {
            "loc": [str(part) for part in err.get("loc", ())],
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Request validation failed", {"fields": fields})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    # Unhandled exceptions are turned into the 500 envelope by RequestContextMiddleware.

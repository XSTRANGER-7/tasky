from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.errors import AppError
from app.core.request_context import new_ulid

REQUEST_ID = re.compile(r"^req_[0-9A-HJKMNP-TV-Z]{26}$")


class _Teapot(AppError):
    status_code = 418
    code = "teapot"


class _Body(BaseModel):
    title: str


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    """The base app plus a few routes that fail in known ways."""

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals must not leak")

    @app.get("/_test/domain")
    async def domain() -> None:
        raise _Teapot("short and stout", details={"spout": True})

    @app.post("/_test/validate")
    async def validate(body: _Body) -> _Body:
        return body

    return app


def test_ulid_is_26_crockford_chars_and_time_sortable() -> None:
    first, second = new_ulid(), new_ulid()
    assert len(first) == 26
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", first)
    assert first[:10] <= second[:10]  # 48-bit timestamp prefix


async def test_generates_request_id(client: httpx.AsyncClient) -> None:
    res = await client.get("/openapi.json")

    assert REQUEST_ID.match(res.headers["x-request-id"])


async def test_request_ids_are_unique(client: httpx.AsyncClient) -> None:
    ids = {(await client.get("/openapi.json")).headers["x-request-id"] for _ in range(20)}

    assert len(ids) == 20


async def test_reuses_well_formed_inbound_id(client: httpx.AsyncClient) -> None:
    res = await client.get("/openapi.json", headers={"X-Request-ID": "edge-7f3a9c21"})

    assert res.headers["x-request-id"] == "edge-7f3a9c21"


@pytest.mark.parametrize(
    "bad", ["short", "has spaces in it", "x" * 129, "inject" + chr(0x2028) + "line"]
)
async def test_replaces_malformed_inbound_id(client: httpx.AsyncClient, bad: str) -> None:
    res = await client.get("/openapi.json", headers={"X-Request-ID": bad.encode("utf-8")})

    assert REQUEST_ID.match(res.headers["x-request-id"])


async def test_unhandled_error_returns_envelope_with_request_id(
    client: httpx.AsyncClient,
) -> None:
    res = await client.get("/_test/boom")

    assert res.status_code == 500
    body = res.json()
    assert body == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
            "details": {},
            "request_id": res.headers["x-request-id"],
        }
    }
    assert "secret internals" not in res.text


async def test_domain_error_uses_its_status_and_code(client: httpx.AsyncClient) -> None:
    res = await client.get("/_test/domain")

    assert res.status_code == 418
    err = res.json()["error"]
    assert err["code"] == "teapot"
    assert err["message"] == "short and stout"
    assert err["details"] == {"spout": True}
    assert err["request_id"] == res.headers["x-request-id"]


async def test_not_found_uses_envelope(client: httpx.AsyncClient) -> None:
    res = await client.get("/nope")

    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "not_found"
    assert err["request_id"] == res.headers["x-request-id"]


async def test_method_not_allowed_uses_envelope(client: httpx.AsyncClient) -> None:
    res = await client.delete("/health")

    assert res.status_code == 405
    assert res.json()["error"]["code"] == "method_not_allowed"


async def test_validation_error_lists_fields(client: httpx.AsyncClient) -> None:
    res = await client.post("/_test/validate", json={})

    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"]["fields"][0]["loc"] == ["body", "title"]


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    res = await client.get("/openapi.json")

    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in res.headers["content-security-policy"]
    assert "strict-transport-security" not in res.headers  # only in production


async def test_cors_allows_configured_origin_only(client: httpx.AsyncClient) -> None:
    allowed = await client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    denied = await client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers

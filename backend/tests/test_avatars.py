"""Profile photos: upload, replace, remove, serve, and where they show up."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import User
from tests.conftest import MakeUser, Person

pytestmark = pytest.mark.db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
AVATAR = "/api/v1/users/me/avatar"


async def _put(client: httpx.AsyncClient, person: Person, data: bytes) -> httpx.Response:
    return await client.put(
        AVATAR,
        content=data,
        headers={**person.headers, "content-type": "application/octet-stream"},
    )


async def _key(db: async_sessionmaker[AsyncSession], person: Person) -> str | None:
    async with db() as s:
        return await s.scalar(select(User.avatar_key).where(User.id == person.id))


async def test_upload_serves_the_photo_everywhere_the_user_appears(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    ada = people["admin"]
    r = await _put(client, ada, PNG)
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url.startswith("/api/v1/avatars/") and url.endswith(".png")

    photo = await client.get(url)  # no token: <img> tags cannot send one
    assert photo.status_code == 200
    assert photo.content == PNG
    assert photo.headers["content-type"] == "image/png"
    assert "immutable" in photo.headers["cache-control"]
    assert photo.headers["x-content-type-options"] == "nosniff"

    me = (await client.get("/api/v1/auth/me", headers=ada.headers)).json()
    assert me["avatar_url"] == url
    directory = (await client.get("/api/v1/users", headers=people["mira"].headers)).json()
    assert next(p for p in directory if p["id"] == str(ada.id))["avatar_url"] == url


async def test_replacing_deletes_the_old_file_and_remove_clears_it(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    ada = people["admin"]
    first = (await _put(client, ada, PNG)).json()["avatar_url"]
    second = (await _put(client, ada, JPEG)).json()["avatar_url"]
    assert second != first and second.endswith(".jpg")
    assert (await client.get(first)).status_code == 404  # old file is gone
    assert (await client.get(second)).headers["content-type"] == "image/jpeg"

    r = await client.delete(AVATAR, headers=ada.headers)
    assert r.status_code == 200 and r.json()["avatar_url"] is None
    assert await _key(db, ada) is None
    assert (await client.get(second)).status_code == 404


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"%PDF-1.7 not a photo", 415),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", 415),  # SVG can carry script
        (b"", 415),
        (PNG + b"\x00" * (2 * 1024 * 1024), 413),
    ],
    ids=["pdf", "svg", "empty", "too-large"],
)
async def test_rejects_non_images_and_large_files(
    client: httpx.AsyncClient, people: dict[str, Person], data: bytes, status: int
) -> None:
    r = await _put(client, people["admin"], data)
    assert r.status_code == status, r.text


async def test_needs_a_session_and_only_serves_avatar_names(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    await make_user("x@example.com")
    r = await client.put(AVATAR, content=PNG)
    assert r.status_code == 401
    for bad in ("..%2Fsecret.png", "abc.png", "0" * 32 + ".svg", "0" * 32 + ".png"):
        assert (await client.get(f"/api/v1/avatars/{bad}")).status_code in (404, 422)

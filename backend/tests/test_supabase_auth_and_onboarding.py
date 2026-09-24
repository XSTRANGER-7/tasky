"""Copying accounts into Supabase Auth (Supabase's admin API faked), and the first-sign-in
onboarding flag."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import User
from app.notifications.worker import Worker
from app.routers import auth as auth_router
from app.services import supabase_auth
from tests.conftest import BuildApp, MakeUser, bearer, client_for
from tests.fakes import FakeSender

pytestmark = pytest.mark.db

ON = {"supabase_url": "https://ref.supabase.co", "supabase_service_role_key": "service-key"}


class FakeSupabase:
    """Just enough of the Supabase Auth admin API: create, list, and a switch to fail."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.fail_for: set[str] = set()
        self.headers: list[httpx.Headers] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.headers.append(request.headers)
        assert request.url.path == "/auth/v1/admin/users"
        if request.method == "GET":
            return httpx.Response(200, json={"users": list(self.users.values())})
        body = json.loads(request.content)
        self.created.append(body)
        email = body["email"].lower()
        if email in self.fail_for:
            return httpx.Response(500, json={"msg": "boom"})
        if email in self.users:
            return httpx.Response(422, json={"error_code": "email_exists", "msg": "exists"})
        self.users[email] = {"id": str(uuid.uuid4()), "email": email}
        return httpx.Response(200, json=self.users[email])


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeSupabase:
    fake = FakeSupabase()
    real = supabase_auth._client
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        supabase_auth, "_client", lambda settings, _transport: real(settings, transport)
    )
    return fake


async def _supabase_ids(db: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID | None]:
    async with db() as s:
        return {u.email: u.supabase_auth_id for u in await s.scalars(select(User))}


async def test_off_unless_url_and_key_are_set(
    settings: Settings,
    db: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    fake: FakeSupabase,
) -> None:
    await make_user("a@example.com")
    async with db() as s:
        assert await supabase_auth.copy_missing(s, settings) == 0
    assert fake.created == []
    assert (await supabase_auth.check(settings))[0] is False


async def test_copies_missing_accounts_once_without_passwords(
    settings: Settings,
    db: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    fake: FakeSupabase,
) -> None:
    on = settings.model_copy(update=ON)
    await make_user("a@example.com", name="Ann")
    await make_user("gone@example.com", is_active=False)
    async with db() as s:
        assert await supabase_auth.copy_missing(s, on) == 1
    async with db() as s:
        assert await supabase_auth.copy_missing(s, on) == 0  # already copied: no second call

    assert len(fake.created) == 1
    sent = fake.created[0]
    assert sent["email"] == "a@example.com"
    assert sent["email_confirm"] is True
    assert sent["user_metadata"]["name"] == "Ann"
    assert sent["app_metadata"]["providers"] == ["email"]
    assert "password" not in json.dumps(sent)
    assert fake.headers[0]["apikey"] == "service-key"
    assert fake.headers[0]["authorization"] == "Bearer service-key"
    ids = await _supabase_ids(db)
    assert ids["a@example.com"] == uuid.UUID(fake.users["a@example.com"]["id"])
    assert ids["gone@example.com"] is None  # deactivated accounts are not copied


async def test_adopts_an_existing_copy_and_retries_failures(
    settings: Settings,
    db: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    fake: FakeSupabase,
) -> None:
    on = settings.model_copy(update=ON)
    await make_user("old@example.com")
    await make_user("flaky@example.com")
    fake.users["old@example.com"] = {"id": str(uuid.uuid4()), "email": "old@example.com"}
    fake.fail_for.add("flaky@example.com")

    async with db() as s:
        assert await supabase_auth.copy_missing(s, on) == 1
    ids = await _supabase_ids(db)
    assert ids["old@example.com"] == uuid.UUID(fake.users["old@example.com"]["id"])
    assert ids["flaky@example.com"] is None

    fake.fail_for.clear()  # Supabase is back: the next run picks it up
    async with db() as s:
        assert await supabase_auth.copy_missing(s, on) == 1
    assert (await _supabase_ids(db))["flaky@example.com"] is not None


async def test_sign_up_copies_right_away(
    build_app: BuildApp,
    db: async_sessionmaker[AsyncSession],
    fake: FakeSupabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_router, "get_sessionmaker", lambda: db)
    async with client_for(build_app(**ON)) as c:
        r = await c.post(
            "/api/v1/auth/register",
            json={"name": "New Person", "email": "new@example.com", "password": "long-enough-1"},
        )
    assert r.status_code == 201, r.text
    assert [b["email"] for b in fake.created] == ["new@example.com"]
    assert (await _supabase_ids(db))["new@example.com"] is not None


async def test_worker_copies_on_its_own_schedule(
    settings: Settings,
    db: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    fake: FakeSupabase,
) -> None:
    now = [0.0]
    worker = Worker(
        settings.model_copy(update=ON), sender=FakeSender(), sessionmaker=db, clock=lambda: now[0]
    )
    await make_user("a@example.com")
    assert await worker.copy_accounts() == 1
    await make_user("b@example.com")
    now[0] = 30.0
    assert await worker.copy_accounts() == 0  # not due yet (every 60 s)
    now[0] = 61.0
    assert await worker.copy_accounts() == 1


async def test_check_reports_whether_the_key_works(settings: Settings) -> None:
    on = settings.model_copy(update=ON)
    good = httpx.MockTransport(lambda _r: httpx.Response(200, json={"users": []}))
    bad = httpx.MockTransport(lambda _r: httpx.Response(401, json={"msg": "no"}))
    assert (await supabase_auth.check(on, transport=good))[0] is True
    ok, message = await supabase_auth.check(on, transport=bad)
    assert not ok and "401" in message


# ---------------------------------------------------------------- onboarding


async def test_new_accounts_start_not_onboarded_and_finishing_sticks(
    client: httpx.AsyncClient, db: async_sessionmaker[AsyncSession]
) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={"name": "Fresh", "email": "fresh@example.com", "password": "long-enough-1"},
    )
    assert r.json()["onboarded"] is False
    r = await client.post(
        "/api/v1/auth/login", json={"email": "fresh@example.com", "password": "long-enough-1"}
    )
    headers = bearer(r.json()["access_token"])
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["onboarded"] is False

    for _ in range(2):  # idempotent
        r = await client.post("/api/v1/auth/me/onboarded", headers=headers)
        assert r.status_code == 200 and r.json()["onboarded"] is True
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["onboarded"] is True


async def test_finishing_onboarding_needs_a_session(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/me/onboarded")).status_code == 401

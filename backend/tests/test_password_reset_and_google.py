"""Forgot/reset password, and sign-in with Google (with Google's endpoints faked)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models import (
    NotificationKind,
    NotificationOutbox,
    OutboxStatus,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.notifications.delivery import REDACTED, process_batch
from app.services import google_oauth
from app.services.google_oauth import GoogleProfile
from tests.conftest import PASSWORD, BuildApp, MakeUser, client_for
from tests.fakes import FakeSender

pytestmark = pytest.mark.db

FORGOT = "/api/v1/auth/forgot-password"
RESET = "/api/v1/auth/reset-password"


async def _reset_mail(db: async_sessionmaker[AsyncSession]) -> list[NotificationOutbox]:
    async with db() as s:
        return list(
            (
                await s.scalars(
                    select(NotificationOutbox).where(
                        NotificationOutbox.kind == NotificationKind.PASSWORD_RESET
                    )
                )
            ).all()
        )


def _token_from(mail: NotificationOutbox) -> str:
    link = next(w for w in mail.body_text.split() if "/reset-password?token=" in w)
    return parse_qs(urlparse(link).query)["token"][0]


# ---------------------------------------------------------------- forgot / reset


async def test_unknown_email_looks_the_same_and_sends_nothing(
    client: httpx.AsyncClient, db: async_sessionmaker[AsyncSession]
) -> None:
    res = await client.post(FORGOT, json={"email": "nobody@example.com"})
    assert res.status_code == 202
    assert await _reset_mail(db) == []


async def test_reset_flow_end_to_end(
    client: httpx.AsyncClient, make_user: MakeUser, db: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("mira@example.com")
    old_session = await client.post(
        "/api/v1/auth/login", json={"email": "mira@example.com", "password": PASSWORD}
    )
    assert old_session.status_code == 200

    assert (await client.post(FORGOT, json={"email": "MIRA@example.com"})).status_code == 202
    [mail] = await _reset_mail(db)
    assert mail.recipient_user_id == user.id
    assert mail.subject == "Reset your Tasky password"
    token = _token_from(mail)

    new_password = "a-brand-new-passphrase"
    res = await client.post(RESET, json={"token": token, "password": new_password})
    assert res.status_code == 204, res.text

    # The new password works, the old one does not, and old sessions were ended.
    ok = await client.post(
        "/api/v1/auth/login", json={"email": "mira@example.com", "password": new_password}
    )
    assert ok.status_code == 200
    old = await client.post(
        "/api/v1/auth/login", json={"email": "mira@example.com", "password": PASSWORD}
    )
    assert old.status_code == 401
    async with db() as s:
        live = await s.scalar(
            select(func.count()).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    assert live == 1  # only the login made after the reset

    # The link is single-use.
    again = await client.post(RESET, json={"token": token, "password": "yet-another-one"})
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "reset_invalid"


async def test_expired_and_forged_links_are_rejected(
    client: httpx.AsyncClient, make_user: MakeUser, db: async_sessionmaker[AsyncSession]
) -> None:
    await make_user("mira@example.com")
    await client.post(FORGOT, json={"email": "mira@example.com"})
    [mail] = await _reset_mail(db)
    async with db() as s:
        await s.execute(
            update(PasswordResetToken).values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await s.commit()
    expired = await client.post(RESET, json={"token": _token_from(mail), "password": "longenough1"})
    assert expired.status_code == 422
    forged = await client.post(RESET, json={"token": "x" * 43, "password": "longenough1"})
    assert forged.status_code == 422


async def test_repeat_requests_are_throttled_per_account(
    client: httpx.AsyncClient, make_user: MakeUser, db: async_sessionmaker[AsyncSession]
) -> None:
    await make_user("mira@example.com")
    for _ in range(3):
        assert (await client.post(FORGOT, json={"email": "mira@example.com"})).status_code == 202
    assert len(await _reset_mail(db)) == 1


async def test_reset_links_are_redacted_once_sent(
    client: httpx.AsyncClient, make_user: MakeUser, db: async_sessionmaker[AsyncSession]
) -> None:
    await make_user("mira@example.com")
    await client.post(FORGOT, json={"email": "mira@example.com"})
    sender = FakeSender()
    async with db() as s:
        result = await process_batch(s, sender)
    assert result.sent == 1
    assert "/reset-password?token=" in sender.sent[0].text  # the person got the link
    [mail] = await _reset_mail(db)
    assert mail.status == OutboxStatus.SENT
    assert mail.body_text == mail.body_html == REDACTED  # ...but it is not kept


async def test_reset_email_is_sent_even_with_notifications_off(
    client: httpx.AsyncClient, make_user: MakeUser, db: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("mira@example.com")
    async with db() as s:
        await s.execute(update(User).where(User.id == user.id).values(notify_email=False))
        await s.commit()
    await client.post(FORGOT, json={"email": "mira@example.com"})
    assert len(await _reset_mail(db)) == 1


# ---------------------------------------------------------------- Google


def _fake_google(monkeypatch: pytest.MonkeyPatch, profile: GoogleProfile) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    async def fetch_profile(settings: object, *, code: str, verifier: str) -> GoogleProfile:
        calls.append({"code": code, "verifier": verifier})
        return profile

    monkeypatch.setattr(google_oauth, "fetch_profile", fetch_profile)
    return calls


def _google_app(build_app: BuildApp, **overrides: object) -> httpx.AsyncClient:
    app = build_app(
        google_client_id="client-123.apps.googleusercontent.com",
        google_client_secret="secret",
        **overrides,
    )
    return client_for(app)


async def _round_trip(c: httpx.AsyncClient, next_path: str = "/") -> httpx.Response:
    start = await c.get(f"/api/v1/auth/google/start?next={next_path}")
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return await c.get(f"/api/v1/auth/google/callback?code=abc&state={state}")


async def test_google_is_off_without_credentials(client: httpx.AsyncClient, db: object) -> None:
    res = await client.get("/api/v1/auth/google/start")
    assert res.status_code == 302
    assert res.headers["location"] == "/login?error=google_disabled"
    assert (await client.get("/api/v1/auth/config")).json()["google_enabled"] is False


async def test_google_start_uses_state_and_pkce(build_app: BuildApp) -> None:
    async with _google_app(build_app) as c:
        assert (await c.get("/api/v1/auth/config")).json()["google_enabled"] is True
        res = await c.get("/api/v1/auth/google/start")
    target = urlparse(res.headers["location"])
    params = parse_qs(target.query)
    assert target.netloc == "accounts.google.com"
    assert params["client_id"] == ["client-123.apps.googleusercontent.com"]
    assert params["redirect_uri"] == ["http://localhost:5173/api/v1/auth/google/callback"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    cookie = res.headers["set-cookie"]
    assert "google_oauth=" in cookie and "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()


async def test_google_creates_an_account_and_signs_in(
    build_app: BuildApp, monkeypatch: pytest.MonkeyPatch, db: async_sessionmaker[AsyncSession]
) -> None:
    calls = _fake_google(
        monkeypatch,
        GoogleProfile(sub="g-1", email="new@example.com", email_verified=True, name="New Person"),
    )
    async with _google_app(build_app) as c:
        res = await _round_trip(c, "/incidents")
        assert res.status_code == 302
        assert res.headers["location"] == "/incidents"
        assert "refresh_token=" in res.headers.get("set-cookie", "")
        me = await c.post("/api/v1/auth/refresh")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "new@example.com"
    assert calls[0]["code"] == "abc" and len(calls[0]["verifier"]) >= 43
    async with db() as s:
        user = await s.scalar(select(User).where(User.email == "new@example.com"))
    assert user is not None
    assert user.google_sub == "g-1"
    assert user.password_hash is None


async def test_google_links_an_existing_account_by_verified_email(
    build_app: BuildApp,
    monkeypatch: pytest.MonkeyPatch,
    make_user: MakeUser,
    db: async_sessionmaker[AsyncSession],
) -> None:
    existing = await make_user("mira@example.com")
    _fake_google(
        monkeypatch,
        GoogleProfile(sub="g-mira", email="mira@example.com", email_verified=True, name="M"),
    )
    async with _google_app(build_app) as c:
        res = await _round_trip(c)
    assert res.headers["location"] == "/"
    async with db() as s:
        user = await s.get(User, existing.id)
    assert user is not None and user.google_sub == "g-mira"
    assert user.password_hash is not None  # the password still works too


@pytest.mark.parametrize(
    ("profile", "overrides", "code"),
    [
        (
            GoogleProfile(sub="g-2", email="x@example.com", email_verified=False, name="X"),
            {},
            "google_email_unverified",
        ),
        (
            GoogleProfile(sub="g-3", email="y@example.com", email_verified=True, name="Y"),
            {"allow_self_register": False},
            "registration_closed",
        ),
    ],
)
async def test_google_refusals_go_back_to_login(
    build_app: BuildApp,
    monkeypatch: pytest.MonkeyPatch,
    db: object,
    profile: GoogleProfile,
    overrides: dict[str, object],
    code: str,
) -> None:
    _fake_google(monkeypatch, profile)
    async with _google_app(build_app, **overrides) as c:
        res = await _round_trip(c)
    assert res.headers["location"] == f"/login?error={code}"
    assert "refresh_token=" not in res.headers.get("set-cookie", "")


async def test_google_callback_rejects_a_forged_state(
    build_app: BuildApp, monkeypatch: pytest.MonkeyPatch, db: object
) -> None:
    calls = _fake_google(
        monkeypatch, GoogleProfile(sub="g", email="z@example.com", email_verified=True, name="Z")
    )
    async with _google_app(build_app) as c:
        await c.get("/api/v1/auth/google/start")
        res = await c.get("/api/v1/auth/google/callback?code=abc&state=attacker-chosen")
    assert res.headers["location"] == "/login?error=google_expired"
    assert calls == []  # the code was never exchanged


async def test_google_next_cannot_leave_the_site(
    build_app: BuildApp, monkeypatch: pytest.MonkeyPatch, db: object
) -> None:
    _fake_google(
        monkeypatch, GoogleProfile(sub="g-4", email="w@example.com", email_verified=True, name="W")
    )
    async with _google_app(build_app) as c:
        res = await _round_trip(c, "//evil.example.com/steal")
    assert res.headers["location"] == "/"

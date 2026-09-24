"""Auth: register, login, access tokens, refresh rotation + reuse detection, logout."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import JWT_ALGORITHM, create_access_token
from app.db.base import utcnow
from app.models import RefreshToken, Role, User
from tests.conftest import (
    PASSWORD,
    TEST_JWT_SECRET,
    BuildApp,
    Login,
    MakeUser,
    bearer,
    client_for,
)

pytestmark = pytest.mark.db

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

Db = async_sessionmaker[AsyncSession]


# ---------------------------------------------------------------- register


async def test_register_creates_member_without_leaking_hash(
    client: httpx.AsyncClient, db: Db
) -> None:
    res = await client.post(
        REGISTER, json={"name": "  Mira  ", "email": "Mira@Example.com", "password": PASSWORD}
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Mira"  # trimmed
    assert "role" not in body  # accounts have no global role; roles live in teams
    assert body["avatar_color"].startswith("#")
    assert "password" not in res.text and "hash" not in res.text

    async with db() as s:
        user = await s.scalar(select(User))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")


async def test_register_duplicate_email_is_case_insensitive(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    await make_user("mira@example.com")

    res = await client.post(
        REGISTER, json={"name": "Other", "email": "MIRA@example.com", "password": PASSWORD}
    )

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": "A", "email": "a@example.com", "password": "short"}, "password"),
        ({"name": "A", "email": "not-an-email", "password": PASSWORD}, "email"),
        ({"name": "   ", "email": "a@example.com", "password": PASSWORD}, "name"),
        ({"name": "A", "email": "a@example.com", "password": "x" * 129}, "password"),
    ],
)
async def test_register_validation(
    client: httpx.AsyncClient, db: Db, payload: dict[str, str], field: str
) -> None:
    res = await client.post(REGISTER, json=payload)

    assert res.status_code == 422
    fields = res.json()["error"]["details"]["fields"]
    assert fields[0]["loc"] == ["body", field]


async def test_register_rejects_unknown_fields(client: httpx.AsyncClient, db: Db) -> None:
    """A client cannot smuggle in its own role."""
    res = await client.post(
        REGISTER,
        json={"name": "A", "email": "a@example.com", "password": PASSWORD, "role": "admin"},
    )

    assert res.status_code == 422


async def test_register_disabled_is_for_team_admins_only(
    build_app: BuildApp, make_user: MakeUser
) -> None:
    """With self-registration closed, the admin of a team may still create accounts (for
    people they then add to their team); ordinary members may not."""
    app = build_app(allow_self_register=False)
    await make_user("admin@example.com", role=Role.ADMIN)
    await make_user("mira@example.com", role=Role.MEMBER)
    new = {"name": "New", "email": "new@example.com", "password": PASSWORD}

    async with client_for(app) as c:
        anonymous = await c.post(REGISTER, json=new)
        member_token = (
            await c.post(LOGIN, json={"email": "mira@example.com", "password": PASSWORD})
        ).json()["access_token"]
        by_member = await c.post(REGISTER, json=new, headers=bearer(member_token))
        token = (
            await c.post(LOGIN, json={"email": "admin@example.com", "password": PASSWORD})
        ).json()["access_token"]
        by_admin = await c.post(REGISTER, json=new, headers=bearer(token))

    assert anonymous.status_code == 403
    assert by_member.status_code == 403
    assert by_admin.status_code == 201


# ---------------------------------------------------------------- login


async def test_login_returns_token_and_sets_strict_httponly_cookie(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    await make_user("mira@example.com")

    res = await client.post(LOGIN, json={"email": "MIRA@example.com", "password": PASSWORD})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["user"]["email"] == "mira@example.com"
    cookie = res.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie
    assert "Secure" not in cookie  # test settings; see the next test


async def test_cookie_is_secure_outside_development(
    build_app: BuildApp, make_user: MakeUser
) -> None:
    app = build_app(cookie_secure=None)  # app_env=test -> Secure
    await make_user("mira@example.com")

    async with client_for(app) as c:
        res = await c.post(LOGIN, json={"email": "mira@example.com", "password": PASSWORD})

    assert "Secure" in res.headers["set-cookie"]


@pytest.mark.parametrize(
    ("email", "password"),
    [("mira@example.com", "wrong-password"), ("nobody@example.com", PASSWORD)],
)
async def test_login_failures_are_indistinguishable(
    client: httpx.AsyncClient, make_user: MakeUser, email: str, password: str
) -> None:
    await make_user("mira@example.com")

    res = await client.post(LOGIN, json={"email": email, "password": password})

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_credentials"
    assert res.json()["error"]["message"] == "Invalid email or password"
    assert "set-cookie" not in res.headers


async def test_login_deactivated_account(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    await make_user("gone@example.com", is_active=False)

    res = await client.post(LOGIN, json={"email": "gone@example.com", "password": PASSWORD})

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "account_disabled"


# ---------------------------------------------------------------- access tokens


async def test_me_requires_a_token(client: httpx.AsyncClient, db: Db) -> None:
    res = await client.get(ME)

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"
    assert res.headers["www-authenticate"] == "Bearer"


async def test_me_with_valid_token(
    client: httpx.AsyncClient, make_user: MakeUser, login: Login
) -> None:
    await make_user("mira@example.com", role=Role.VIEWER)
    token = await login("mira@example.com")

    res = await client.get(ME, headers=bearer(token))

    assert res.status_code == 200
    assert res.json()["email"] == "mira@example.com"
    assert "role" not in res.json()


async def test_expired_access_token(
    client: httpx.AsyncClient, make_user: MakeUser, settings: Settings
) -> None:
    user = await make_user()
    past = utcnow() - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(user.id), "typ": "access", "iat": past, "exp": past + timedelta(minutes=15)},
        TEST_JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    res = await client.get(ME, headers=bearer(token))

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "token_expired"


@pytest.mark.parametrize(
    "forge",
    [
        pytest.param(lambda uid: "not-a-jwt", id="garbage"),
        pytest.param(
            lambda uid: jwt.encode(
                {"sub": uid, "typ": "access", "iat": utcnow(), "exp": utcnow() + timedelta(1)},
                "some-other-secret-some-other-secret",
                algorithm="HS256",
            ),
            id="wrong-secret",
        ),
        pytest.param(
            lambda uid: jwt.encode(
                {"sub": uid, "typ": "refresh", "iat": utcnow(), "exp": utcnow() + timedelta(1)},
                TEST_JWT_SECRET,
                algorithm="HS256",
            ),
            id="wrong-type",
        ),
        pytest.param(
            lambda uid: jwt.encode(
                {"sub": uid, "typ": "access", "iat": utcnow(), "exp": utcnow() + timedelta(1)},
                None,
                algorithm="none",
            ),
            id="alg-none",
        ),
    ],
)
async def test_forged_tokens_are_rejected(
    client: httpx.AsyncClient, make_user: MakeUser, forge: object
) -> None:
    user = await make_user()
    token = forge(str(user.id))  # type: ignore[operator]

    res = await client.get(ME, headers=bearer(token))

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "token_invalid"


async def test_token_for_deleted_user_is_rejected(
    client: httpx.AsyncClient, db: Db, settings: Settings
) -> None:
    token = create_access_token(uuid.uuid4(), settings).token

    res = await client.get(ME, headers=bearer(token))

    assert res.status_code == 401


# ---------------------------------------------------------------- refresh


async def test_refresh_rotates_the_cookie(
    client: httpx.AsyncClient, make_user: MakeUser, login: Login, db: Db
) -> None:
    await make_user("mira@example.com")
    await login("mira@example.com")
    first = client.cookies["refresh_token"]

    res = await client.post(REFRESH)

    assert res.status_code == 200, res.text
    second = client.cookies["refresh_token"]
    assert second != first
    assert res.json()["user"]["email"] == "mira@example.com"
    me = await client.get(ME, headers=bearer(res.json()["access_token"]))
    assert me.status_code == 200

    async with db() as s:
        rows = (await s.scalars(select(RefreshToken).order_by(RefreshToken.created_at))).all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None
    assert rows[0].replaced_by_id == rows[1].id
    assert rows[1].revoked_at is None


async def test_reusing_a_rotated_token_revokes_every_session(
    client: httpx.AsyncClient, make_user: MakeUser, login: Login, db: Db
) -> None:
    await make_user("mira@example.com")
    await login("mira@example.com")
    stolen = client.cookies["refresh_token"]
    assert (await client.post(REFRESH)).status_code == 200  # legitimate rotation
    current = client.cookies["refresh_token"]

    client.cookies.set("refresh_token", stolen, path="/api/v1/auth")
    replay = await client.post(REFRESH)

    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_reused"
    # The legitimate, newer token died with it: the attacker cannot outlive detection.
    client.cookies.set("refresh_token", current, path="/api/v1/auth")
    after = await client.post(REFRESH)
    assert after.status_code == 401
    async with db() as s:
        active = await s.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
        assert active.all() == []


async def test_refresh_without_cookie(client: httpx.AsyncClient, db: Db) -> None:
    res = await client.post(REFRESH)

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "refresh_missing"


async def test_rejected_refresh_clears_the_cookie(client: httpx.AsyncClient, db: Db) -> None:
    client.cookies.set("refresh_token", "bogus", path="/api/v1/auth")

    res = await client.post(REFRESH)

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "refresh_invalid"
    assert 'refresh_token=""' in res.headers["set-cookie"]
    assert "Max-Age=0" in res.headers["set-cookie"]


async def test_expired_refresh_token(
    client: httpx.AsyncClient, make_user: MakeUser, login: Login, db: Db
) -> None:
    await make_user("mira@example.com")
    await login("mira@example.com")
    async with db() as s:
        row = await s.scalar(select(RefreshToken))
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        await s.commit()

    res = await client.post(REFRESH)

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "refresh_expired"


# ---------------------------------------------------------------- logout


async def test_logout_revokes_the_refresh_token(
    client: httpx.AsyncClient, make_user: MakeUser, login: Login
) -> None:
    await make_user("mira@example.com")
    await login("mira@example.com")
    token = client.cookies["refresh_token"]

    res = await client.post(LOGOUT)

    assert res.status_code == 204
    assert "Max-Age=0" in res.headers["set-cookie"]
    client.cookies.set("refresh_token", token, path="/api/v1/auth")
    assert (await client.post(REFRESH)).status_code == 401


async def test_logout_is_idempotent(client: httpx.AsyncClient, db: Db) -> None:
    assert (await client.post(LOGOUT)).status_code == 204
    client.cookies.set("refresh_token", "unknown", path="/api/v1/auth")
    assert (await client.post(LOGOUT)).status_code == 204


# ---------------------------------------------------------------- rate limits


async def test_login_is_rate_limited_per_ip(build_app: BuildApp) -> None:
    app = build_app(login_rate_limit_per_min=5)
    creds = {"email": "nobody@example.com", "password": "whatever-123"}

    async with client_for(app) as c:
        statuses = [(await c.post(LOGIN, json=creds)).status_code for _ in range(5)]
        blocked = await c.post(LOGIN, json=creds)

    assert statuses == [401] * 5
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0
    assert blocked.headers["ratelimit-limit"] == "5"
    assert blocked.headers["ratelimit-remaining"] == "0"


async def test_rate_limit_headers_on_success(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    await make_user("mira@example.com")

    res = await client.post(LOGIN, json={"email": "mira@example.com", "password": PASSWORD})

    assert res.headers["ratelimit-limit"] == "1000"
    assert res.headers["ratelimit-remaining"] == "999"


async def test_register_is_rate_limited(build_app: BuildApp) -> None:
    app = build_app(register_rate_limit_per_min=3)

    async with client_for(app) as c:
        statuses = [
            (
                await c.post(
                    REGISTER,
                    json={"name": "U", "email": f"u{i}@example.com", "password": PASSWORD},
                )
            ).status_code
            for i in range(4)
        ]

    assert statuses == [201, 201, 201, 429]

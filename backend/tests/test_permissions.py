"""Roles and ownership on /users, plus the reusable role gate."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.core.deps import get_team_admin
from app.models import Role, User
from tests.conftest import Login, MakeUser, bearer

pytestmark = pytest.mark.db

USERS = "/api/v1/users"


@pytest.fixture
async def team(make_user: MakeUser) -> dict[str, User]:
    return {
        "admin": await make_user("admin@example.com", role=Role.ADMIN, name="Ada Admin"),
        "member": await make_user("mira@example.com", role=Role.MEMBER, name="Mira Member"),
        "viewer": await make_user("sam@example.com", role=Role.VIEWER, name="Sam Viewer"),
        "inactive": await make_user("old@example.com", is_active=False, name="Old Timer"),
    }


# ---------------------------------------------------------------- listing


async def test_list_users_requires_auth(client: httpx.AsyncClient, db: object) -> None:
    assert (await client.get(USERS)).status_code == 401


@pytest.mark.parametrize("who", ["member", "viewer"])
async def test_non_admins_see_active_teammates_public_fields(
    client: httpx.AsyncClient, team: dict[str, User], login: Login, who: str
) -> None:
    token = await login(team[who].email)

    res = await client.get(USERS, headers=bearer(token))

    assert res.status_code == 200
    users = res.json()
    assert [u["name"] for u in users] == ["Ada Admin", "Mira Member", "Sam Viewer"]
    assert set(users[0]) == {"id", "name", "email", "role", "avatar_color", "avatar_url"}


async def test_admin_sees_everyone_with_all_fields(
    client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    token = await login("admin@example.com")

    res = await client.get(USERS, headers=bearer(token))

    names = [u["name"] for u in res.json()]
    assert "Old Timer" in names
    assert {"is_active", "notify_email", "created_at"} <= set(res.json()[0])


# ---------------------------------------------------------------- self-service


async def test_user_can_edit_own_profile(
    client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    token = await login("mira@example.com")

    res = await client.patch(
        f"{USERS}/{team['member'].id}",
        json={"name": "Mira M.", "notify_email": False},
        headers=bearer(token),
    )

    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Mira M."
    assert res.json()["notify_email"] is False


@pytest.mark.parametrize("field", [{"role": "admin"}, {"is_active": False}])
async def test_accounts_have_no_role_or_status_to_edit(
    client: httpx.AsyncClient, team: dict[str, User], login: Login, field: dict[str, object]
) -> None:
    """There is no platform-wide admin: roles live in teams, so a profile has no role."""
    token = await login("admin@example.com")

    res = await client.patch(f"{USERS}/{team['admin'].id}", json=field, headers=bearer(token))

    assert res.status_code == 422


@pytest.mark.parametrize("who", ["admin", "member", "viewer"])
async def test_nobody_can_edit_someone_elses_profile(
    client: httpx.AsyncClient, team: dict[str, User], login: Login, who: str
) -> None:
    """Not even a team admin: they manage who is in their team, not other accounts."""
    token = await login(team[who].email)
    other = team["member"] if who != "member" else team["admin"]

    res = await client.patch(f"{USERS}/{other.id}", json={"name": "Hacked"}, headers=bearer(token))

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------- team admin powers


async def _team_id(client: httpx.AsyncClient, token: str) -> str:
    mine = (await client.get("/api/v1/teams/mine", headers=bearer(token))).json()
    return str(mine["teams"][0]["id"])


async def test_team_role_change_takes_effect_on_the_next_request(
    client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    member_token = await login("mira@example.com")
    admin_token = await login("admin@example.com")
    team_id = await _team_id(client, admin_token)

    promote = await client.patch(
        f"/api/v1/teams/{team_id}/members/{team['member'].id}",
        json={"role": "admin"},
        headers=bearer(admin_token),
    )
    assert promote.status_code == 200

    # Same (unexpired) access token -- the role is read from the DB, not the JWT.
    res = await client.get(USERS, headers=bearer(member_token))
    assert "Old Timer" in [u["name"] for u in res.json()]


async def test_last_team_admin_cannot_step_down(
    client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    token = await login("admin@example.com")
    team_id = await _team_id(client, token)

    res = await client.patch(
        f"/api/v1/teams/{team_id}/members/{team['admin'].id}",
        json={"role": "member"},
        headers=bearer(token),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "last_admin"


async def test_team_admin_can_step_down_when_another_admin_exists(
    client: httpx.AsyncClient, team: dict[str, User], make_user: MakeUser, login: Login
) -> None:
    await make_user("second@example.com", role=Role.ADMIN)
    token = await login("admin@example.com")
    team_id = await _team_id(client, token)

    res = await client.patch(
        f"/api/v1/teams/{team_id}/members/{team['admin'].id}",
        json={"role": "member"},
        headers=bearer(token),
    )

    assert res.status_code == 200
    assert res.json()["role"] == "member"


# ---------------------------------------------------------------- validation


async def test_unknown_user_is_403(
    client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    token = await login("admin@example.com")

    res = await client.patch(f"{USERS}/{uuid.uuid4()}", json={"name": "x"}, headers=bearer(token))

    assert res.status_code == 403  # only your own profile exists for you


async def test_bad_uuid_is_422(
    client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    token = await login("admin@example.com")

    res = await client.patch(f"{USERS}/not-a-uuid", json={"name": "x"}, headers=bearer(token))

    assert res.status_code == 422


@pytest.mark.parametrize(
    "body", [{"name": None}, {"role": "superuser"}, {"name": ""}, {"email": "x@example.com"}]
)
async def test_invalid_updates_are_422(
    client: httpx.AsyncClient, team: dict[str, User], login: Login, body: dict[str, object]
) -> None:
    token = await login("mira@example.com")

    res = await client.patch(f"{USERS}/{team['member'].id}", json=body, headers=bearer(token))

    assert res.status_code == 422, res.text


# ---------------------------------------------------------------- team admin gate


async def test_team_admin_gate(
    app: FastAPI, client: httpx.AsyncClient, team: dict[str, User], login: Login
) -> None:
    @app.get("/_test/team-admin-only", dependencies=[Depends(get_team_admin)])
    async def team_admin_only() -> dict[str, bool]:
        return {"ok": True}

    admin, viewer = await login("admin@example.com"), await login("sam@example.com")

    assert (await client.get("/_test/team-admin-only")).status_code == 401
    assert (await client.get("/_test/team-admin-only", headers=bearer(viewer))).status_code == 403
    assert (await client.get("/_test/team-admin-only", headers=bearer(admin))).status_code == 200

"""Teams: isolation between teams, the join-request flow, member management, and what a
team's admins (and only they) may do. There is no platform-wide admin."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import (
    InAppNotification,
    IncidentWatcher,
    NotificationKind,
    NotificationOutbox,
    Role,
    Team,
    TeamMembership,
    TeamRole,
)
from tests.conftest import MakeUser, Person

pytestmark = pytest.mark.db

TEAMS = "/api/v1/teams"


def in_team(person: Person, team_id: object) -> dict[str, str]:
    return {**person.headers, "X-Team-Id": str(team_id)}


async def new_team(client: httpx.AsyncClient, creator: Person, name: str = "Payments") -> str:
    res = await client.post(TEAMS, json={"name": name}, headers=creator.headers)
    assert res.status_code == 201, res.text
    assert res.json()["my_role"] == "admin"  # whoever creates a team is its admin
    return str(res.json()["id"])


async def add(
    client: httpx.AsyncClient, admin: Person, team_id: str, email: str, role: str
) -> None:
    res = await client.post(
        f"{TEAMS}/{team_id}/members", json={"email": email, "role": role}, headers=admin.headers
    )
    assert res.status_code == 201, res.text


async def test_creator_becomes_admin_and_lists_teams(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    team_id = await new_team(client, people["mira"], "Payments Squad")
    mine = (await client.get(f"{TEAMS}/mine", headers=people["mira"].headers)).json()
    names = {t["name"]: t for t in mine["teams"]}
    assert set(names) == {"Test Team", "Payments Squad"}
    assert names["Payments Squad"]["slug"] == "payments-squad"
    assert names["Payments Squad"]["member_count"] == 1
    assert names["Payments Squad"]["my_role"] == "admin"
    assert names["Test Team"]["my_role"] == "member"  # admin here, member there
    # Same name again gets a distinct slug.
    other = await client.post(TEAMS, json={"name": "Payments Squad"}, headers=people["max"].headers)
    assert other.json()["slug"] == "payments-squad-2"
    assert other.json()["id"] != team_id


async def test_viewers_can_create_their_own_team_too(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    sam = people["sam"]  # a viewer in Test Team
    team_id = await new_team(client, sam, "Sam's Lab")
    res = await client.post(
        "/api/v1/incidents", json={"title": "Lab printer on fire"}, headers=in_team(sam, team_id)
    )
    assert res.status_code == 201  # admin of his own team, still read-only in Test Team
    blocked = await client.post(
        "/api/v1/incidents",
        json={"title": "Not here"},
        headers=in_team(sam, await _test_team(client, sam)),
    )
    assert blocked.status_code == 403


async def _test_team(client: httpx.AsyncClient, person: Person) -> str:
    mine = (await client.get(f"{TEAMS}/mine", headers=person.headers)).json()
    return str(next(t["id"] for t in mine["teams"] if t["slug"] == "test-team"))


async def test_several_teams_need_the_team_header(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira = people["mira"]
    await new_team(client, mira)
    res = await client.get("/api/v1/incidents", headers=mira.headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "team_required"


async def test_no_team_means_onboarding(
    client: httpx.AsyncClient, make_user: MakeUser, settings: Settings
) -> None:
    loner = Person(await make_user("loner@example.com", team=False), settings)
    res = await client.get("/api/v1/incidents", headers=loner.headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "no_team"
    # Team routes still work: that is how they get a team.
    mine = (await client.get(f"{TEAMS}/mine", headers=loner.headers)).json()
    assert mine == {"teams": [], "requests": []}


async def test_teams_cannot_see_each_others_incidents(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira, "Payments")
    # Mira reports in Payments; Max is only in the shared Test Team.
    res = await client.post(
        "/api/v1/incidents",
        json={"title": "Card declines spike"},
        headers=in_team(mira, payments),
    )
    assert res.status_code == 201, res.text
    secret = res.json()
    assert secret["team_id"] == payments

    # Max cannot list, open, comment on, or even address the Payments incident.
    listed = (await client.get("/api/v1/incidents", headers=max_.headers)).json()
    assert secret["key"] not in [i["key"] for i in listed["items"]]
    assert (
        await client.get(f"/api/v1/incidents/{secret['key']}", headers=max_.headers)
    ).status_code == 404
    comment = await client.post(
        f"/api/v1/incidents/{secret['key']}/comments", json={"body": "hi"}, headers=max_.headers
    )
    assert comment.status_code == 404
    forced = await client.get("/api/v1/incidents", headers=in_team(max_, payments))
    assert forced.status_code == 403
    assert forced.json()["error"]["code"] == "not_team_member"

    # Each team's dashboard counts only its own incidents.
    dash = (await client.get("/api/v1/dashboard/summary", headers=in_team(mira, payments))).json()
    assert sum(dash["counts"].values()) == 1
    test_team_dash = (await client.get("/api/v1/dashboard/summary", headers=max_.headers)).json()
    assert sum(test_team_dash["counts"].values()) == 0


async def test_an_admin_of_one_team_has_no_power_in_another(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    """The heart of "no single admin": Ada administers Test Team, not Mira's team."""
    ada, mira = people["admin"], people["mira"]
    payments = await new_team(client, mira)
    inc = (
        await client.post(
            "/api/v1/incidents",
            json={"title": "Refund queue stuck"},
            headers=in_team(mira, payments),
        )
    ).json()

    assert (
        await client.get("/api/v1/incidents", headers=in_team(ada, payments))
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/incidents/{inc['key']}", headers=ada.headers)
    ).status_code == 404
    assert (await client.get(f"{TEAMS}/{payments}/members", headers=ada.headers)).status_code == 403
    assert (
        await client.get(f"{TEAMS}/{payments}/join-requests", headers=ada.headers)
    ).status_code == 403
    assert (await client.delete(f"{TEAMS}/{payments}", headers=ada.headers)).status_code == 403
    rename = await client.patch(
        f"{TEAMS}/{payments}", json={"name": "Mine now"}, headers=ada.headers
    )
    assert rename.status_code == 403


async def test_comment_edit_cannot_cross_teams(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    inc = (
        await client.post(
            "/api/v1/incidents", json={"title": "Refunds stuck"}, headers=in_team(mira, payments)
        )
    ).json()
    comment = (
        await client.post(
            f"/api/v1/incidents/{inc['key']}/comments",
            json={"body": "looking"},
            headers=in_team(mira, payments),
        )
    ).json()
    # Even with the comment id, someone outside the team gets a 404, not a 403.
    res = await client.patch(
        f"/api/v1/comments/{comment['id']}", json={"body": "hijacked"}, headers=max_.headers
    )
    assert res.status_code == 404


async def test_directory_and_assignment_stay_inside_the_team(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    directory = (await client.get("/api/v1/users", headers=in_team(mira, payments))).json()
    assert [(u["name"], u["role"]) for u in directory] == [("Mira Member", "admin")]
    res = await client.post(
        "/api/v1/incidents",
        json={"title": "Payouts delayed", "assignee_id": str(max_.id)},
        headers=in_team(mira, payments),
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_assignee"


# ---------------------------------------------------------------- join requests


async def test_join_request_notifies_admins_and_approval_grants_access(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)

    found = (await client.get(f"{TEAMS}/discover?q=pay", headers=max_.headers)).json()
    assert [t["name"] for t in found] == ["Payments"]
    assert found[0]["my_role"] is None

    req = await client.post(
        f"{TEAMS}/{payments}/join-requests",
        json={"message": "I'm on call for payouts"},
        headers=max_.headers,
    )
    assert req.status_code == 201, req.text
    request = req.json()
    assert request["status"] == "pending"
    # Asking twice is the same request.
    again = await client.post(f"{TEAMS}/{payments}/join-requests", json={}, headers=max_.headers)
    assert again.json()["id"] == request["id"]

    # The team's admin (its creator) got an email and an in-app notification.
    async with db() as s:
        mail = (
            await s.scalars(
                select(NotificationOutbox).where(
                    NotificationOutbox.kind == NotificationKind.TEAM_JOIN_REQUESTED
                )
            )
        ).all()
        in_app = (
            await s.scalars(
                select(InAppNotification).where(
                    InAppNotification.kind == NotificationKind.TEAM_JOIN_REQUESTED
                )
            )
        ).all()
    assert [m.recipient_user_id for m in mail] == [mira.id]
    assert mail[0].incident_id is None
    assert str(mail[0].team_id) == payments
    assert "Max Member asked to join Payments" in mail[0].subject
    assert "on call for payouts" in mail[0].body_text
    assert [n.user_id for n in in_app] == [mira.id]
    assert in_app[0].link == f"/team/requests?team={payments}"

    feed = (await client.get("/api/v1/notifications", headers=mira.headers)).json()
    item = next(i for i in feed["items"] if i["kind"] == "team_join_requested")
    assert item["incident_key"] is None
    assert item["link"] == f"/team/requests?team={payments}"

    # Pending: Max still has no access.
    blocked = await client.get("/api/v1/incidents", headers=in_team(max_, payments))
    assert blocked.status_code == 403

    review = (await client.get(f"{TEAMS}/join-requests/review", headers=mira.headers)).json()
    assert [r["id"] for r in review] == [request["id"]]
    approved = await client.post(
        f"{TEAMS}/join-requests/{request['id']}/approve",
        json={"role": "viewer"},
        headers=mira.headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["granted_role"] == "viewer"
    assert approved.json()["decided_by"]["id"] == str(mira.id)

    # Now Max is in, as a viewer: can read, cannot create.
    assert (
        await client.get("/api/v1/incidents", headers=in_team(max_, payments))
    ).status_code == 200
    create = await client.post(
        "/api/v1/incidents", json={"title": "Try to write"}, headers=in_team(max_, payments)
    )
    assert create.status_code == 403

    # ...and was told.
    async with db() as s:
        told = await s.scalar(
            select(func.count()).where(
                NotificationOutbox.kind == NotificationKind.TEAM_JOIN_APPROVED,
                NotificationOutbox.recipient_user_id == max_.id,
            )
        )
    assert told == 1

    # A decided request cannot be decided again.
    twice = await client.post(f"{TEAMS}/join-requests/{request['id']}/reject", headers=mira.headers)
    assert twice.status_code == 409
    assert twice.json()["error"]["code"] == "request_decided"


async def test_approval_defaults_to_member(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    payments = await new_team(client, people["mira"])
    request = (
        await client.post(
            f"{TEAMS}/{payments}/join-requests", json={}, headers=people["max"].headers
        )
    ).json()
    approved = await client.post(
        f"{TEAMS}/join-requests/{request['id']}/approve", headers=people["mira"].headers
    )
    assert approved.json()["granted_role"] == "member"


async def test_only_team_admins_decide_and_rejection_is_reported(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    request = (
        await client.post(f"{TEAMS}/{payments}/join-requests", json={}, headers=max_.headers)
    ).json()

    # Ada is an admin, but of a different team: no say here.
    for stranger in (people["sam"], people["admin"]):
        res = await client.post(
            f"{TEAMS}/join-requests/{request['id']}/approve", headers=stranger.headers
        )
        assert res.status_code == 403

    rejected = await client.post(
        f"{TEAMS}/join-requests/{request['id']}/reject", headers=mira.headers
    )
    assert rejected.json()["status"] == "rejected"
    async with db() as s:
        n = await s.scalar(
            select(func.count()).where(
                InAppNotification.kind == NotificationKind.TEAM_JOIN_REJECTED,
                InAppNotification.user_id == max_.id,
            )
        )
    assert n == 1
    # Rejected people can ask again later.
    retry = await client.post(f"{TEAMS}/{payments}/join-requests", json={}, headers=max_.headers)
    assert retry.status_code == 201
    assert retry.json()["id"] != request["id"]


async def test_members_cannot_request_again_and_requesters_can_cancel(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    own = await client.post(f"{TEAMS}/{payments}/join-requests", json={}, headers=mira.headers)
    assert own.status_code == 409
    assert own.json()["error"]["code"] == "already_member"

    request = (
        await client.post(f"{TEAMS}/{payments}/join-requests", json={}, headers=max_.headers)
    ).json()
    not_yours = await client.post(
        f"{TEAMS}/join-requests/{request['id']}/cancel", headers=mira.headers
    )
    assert not_yours.status_code == 404
    cancelled = await client.post(
        f"{TEAMS}/join-requests/{request['id']}/cancel", headers=max_.headers
    )
    assert cancelled.json()["status"] == "cancelled"


# ---------------------------------------------------------------- members


async def test_admins_make_co_admins_and_a_team_always_keeps_one(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    await add(client, mira, payments, "max@example.com", "member")

    # A member cannot change roles.
    res = await client.patch(
        f"{TEAMS}/{payments}/members/{max_.id}", json={"role": "admin"}, headers=max_.headers
    )
    assert res.status_code == 403

    # The only admin can neither step down nor leave...
    step_down = await client.patch(
        f"{TEAMS}/{payments}/members/{mira.id}", json={"role": "member"}, headers=mira.headers
    )
    assert step_down.status_code == 409
    assert step_down.json()["error"]["code"] == "last_admin"
    leave = await client.delete(f"{TEAMS}/{payments}/members/{mira.id}", headers=mira.headers)
    assert leave.status_code == 409

    # ...until there is a co-admin, who then has the same powers.
    promote = await client.patch(
        f"{TEAMS}/{payments}/members/{max_.id}", json={"role": "admin"}, headers=mira.headers
    )
    assert promote.json()["role"] == "admin"
    demote_creator = await client.patch(
        f"{TEAMS}/{payments}/members/{mira.id}", json={"role": "member"}, headers=max_.headers
    )
    assert demote_creator.status_code == 200
    leave = await client.delete(f"{TEAMS}/{payments}/members/{mira.id}", headers=mira.headers)
    assert leave.status_code == 204


async def test_removed_members_lose_access_and_stop_watching(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    await add(client, mira, payments, "max@example.com", "member")
    inc = (
        await client.post(
            "/api/v1/incidents",
            json={"title": "Payout batch failed"},
            headers=in_team(mira, payments),
        )
    ).json()
    watch = await client.post(
        f"/api/v1/incidents/{inc['key']}/watch", headers=in_team(max_, payments)
    )
    assert watch.status_code == 200

    removed = await client.delete(f"{TEAMS}/{payments}/members/{max_.id}", headers=mira.headers)
    assert removed.status_code == 204
    after = await client.get(f"/api/v1/incidents/{inc['key']}", headers=in_team(max_, payments))
    assert after.status_code == 403
    async with db() as s:
        watching = await s.scalar(select(func.count()).where(IncidentWatcher.user_id == max_.id))
    assert watching == 0


async def test_only_team_admins_delete_a_team_and_everything_goes(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    await add(client, mira, payments, "max@example.com", "member")
    await client.post(
        "/api/v1/incidents", json={"title": "Ledger mismatch"}, headers=in_team(mira, payments)
    )
    assert (await client.delete(f"{TEAMS}/{payments}", headers=max_.headers)).status_code == 403
    assert (await client.delete(f"{TEAMS}/{payments}", headers=mira.headers)).status_code == 204
    async with db() as s:
        assert await s.get(Team, uuid.UUID(payments)) is None
        left = await s.scalar(
            select(func.count()).where(TeamMembership.team_id == uuid.UUID(payments))
        )
    assert left == 0


# ---------------------------------------------------------------- team admin tools


async def test_admin_console_is_gone(client: httpx.AsyncClient, people: dict[str, Person]) -> None:
    for path in ("overview", "users", "teams", "join-requests"):
        res = await client.get(f"/api/v1/admin/{path}", headers=people["admin"].headers)
        assert res.status_code == 404, path


async def test_email_outbox_is_per_team_and_for_its_admins(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    # Mail about Payments: Max asks to join, so Mira (its admin) is emailed.
    await client.post(f"{TEAMS}/{payments}/join-requests", json={}, headers=max_.headers)

    mine = (await client.get("/api/v1/admin/outbox", headers=in_team(mira, payments))).json()
    assert [r["kind"] for r in mine["items"]] == ["team_join_requested"]
    assert mine["counts"]["pending"] == 1

    # Test Team's admin (Ada) sees none of Payments' mail; a member sees no outbox at all.
    ada_view = (await client.get("/api/v1/admin/outbox", headers=people["admin"].headers)).json()
    assert ada_view["items"] == []
    assert (await client.get("/api/v1/admin/outbox", headers=max_.headers)).status_code == 403
    assert (await client.get("/api/v1/admin/settings", headers=max_.headers)).status_code == 403
    assert (
        await client.get("/api/v1/admin/settings", headers=in_team(mira, payments))
    ).status_code == 200


async def test_role_enum_mapping_matches_permissions() -> None:
    assert [r.value for r in TeamRole] == ["admin", "member", "viewer"]
    assert TeamRole.ADMIN.as_role() == Role.ADMIN
    assert TeamRole.MEMBER.as_role() == Role.MEMBER
    assert TeamRole.VIEWER.as_role() == Role.VIEWER


# ---------------------------------------------------------------- membership emails


async def _mail_to(
    db: async_sessionmaker[AsyncSession], person: Person
) -> list[NotificationOutbox]:
    async with db() as s:
        rows = await s.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.recipient_user_id == person.id)
            .order_by(NotificationOutbox.created_at)
        )
        return list(rows.all())


async def test_people_are_emailed_when_added_promoted_and_removed(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)

    await add(client, mira, payments, "max@example.com", "member")
    await client.patch(
        f"{TEAMS}/{payments}/members/{max_.id}", json={"role": "admin"}, headers=mira.headers
    )
    await client.patch(
        f"{TEAMS}/{payments}/members/{max_.id}", json={"role": "viewer"}, headers=mira.headers
    )
    await client.delete(f"{TEAMS}/{payments}/members/{max_.id}", headers=mira.headers)

    mail = await _mail_to(db, max_)
    assert [(m.kind.value, m.subject) for m in mail] == [
        ("team_member_added", "Mira Member added you to Payments"),
        ("team_role_changed", "You are now an admin of Payments"),
        ("team_role_changed", "You are now a viewer of Payments"),
        ("team_member_removed", "You were removed from Payments"),
    ]
    assert {str(m.team_id) for m in mail} == {payments}
    assert "as a member" in mail[0].body_text
    # ...and the same in the app, where the removal points at the team finder.
    feed = (await client.get("/api/v1/notifications", headers=max_.headers)).json()
    links = {n["kind"]: n["link"] for n in feed["items"]}
    assert links["team_member_added"] == f"/?team={payments}"
    assert links["team_member_removed"] == "/?find=team"


async def test_leaving_a_team_yourself_sends_no_email(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]
    payments = await new_team(client, mira)
    await add(client, mira, payments, "max@example.com", "member")
    left = await client.delete(f"{TEAMS}/{payments}/members/{max_.id}", headers=max_.headers)
    assert left.status_code == 204
    kinds = [m.kind.value for m in await _mail_to(db, max_)]
    assert kinds == ["team_member_added"]  # nothing for leaving


async def test_assigning_an_incident_emails_the_assignee(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    db: async_sessionmaker[AsyncSession],
) -> None:
    mira, max_ = people["mira"], people["max"]  # both members of Test Team
    inc = (
        await client.post(
            "/api/v1/incidents", json={"title": "Queue backlog"}, headers=mira.headers
        )
    ).json()
    res = await client.post(
        f"/api/v1/incidents/{inc['key']}/assign",
        json={"assignee_id": str(max_.id)},
        headers=mira.headers,
    )
    assert res.status_code == 200, res.text
    [mail] = await _mail_to(db, max_)
    assert mail.kind == NotificationKind.INCIDENT_ASSIGNED
    assert mail.subject == f"[{inc['key']}] Assigned to you: Queue backlog"
    assert str(mail.team_id) == inc["team_id"]

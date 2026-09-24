"""Who gets notified, through the real API (spec 9.1, 9.9, 16)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.base import utcnow
from app.models import (
    EventType,
    InAppNotification,
    Incident,
    IncidentEvent,
    NotificationKind,
    NotificationOutbox,
    OutboxStatus,
    User,
)
from app.notifications import sla_checker
from app.services import incident_service
from tests.conftest import CreateIncident, MakeUser, Person

pytestmark = pytest.mark.db
Db = async_sessionmaker[AsyncSession]
URL = "/api/v1/incidents"
K = NotificationKind


async def emails(db: Db) -> list[tuple[str, NotificationKind]]:
    async with db() as s:
        rows = (
            await s.execute(
                select(User.name, NotificationOutbox.kind)
                .join(User, User.id == NotificationOutbox.recipient_user_id)
                .order_by(User.name)
            )
        ).all()
    return [(name, kind) for name, kind in rows]


async def in_app(db: Db) -> list[tuple[str, NotificationKind]]:
    async with db() as s:
        rows = (
            await s.execute(
                select(User.name, InAppNotification.kind)
                .join(User, User.id == InAppNotification.user_id)
                .order_by(User.name)
            )
        ).all()
    return [(name, kind) for name, kind in rows]


async def clear(db: Db) -> None:
    async with db() as s:
        await s.execute(NotificationOutbox.__table__.delete())
        await s.execute(InAppNotification.__table__.delete())
        await s.commit()


async def watch(client: httpx.AsyncClient, key: object, who: Person) -> None:
    res = await client.post(f"{URL}/{key}/watch", headers=who.headers)
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------- assignment


async def test_assign_emails_and_notifies_the_assignee_once(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident()
    await watch(client, inc["key"], people["admin"])

    await client.post(
        f"{URL}/{inc['key']}/assign",
        json={"assignee_id": str(people["max"].id)},
        headers=people["mira"].headers,
    )

    assert await emails(db) == [
        ("Ada Admin", K.INCIDENT_ASSIGNED),  # the team's admin hears about every assignment
        ("Max Member", K.INCIDENT_ASSIGNED),
    ]
    assert await in_app(db) == [
        ("Ada Admin", K.INCIDENT_ASSIGNED),  # admin and watcher: still one notification
        ("Max Member", K.INCIDENT_ASSIGNED),
    ]


async def test_assignment_at_creation_notifies_the_assignee(
    people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    await create_incident(assignee_id=str(people["max"].id))

    assert await emails(db) == [
        ("Ada Admin", K.INCIDENT_ASSIGNED),
        ("Max Member", K.INCIDENT_ASSIGNED),
    ]


async def test_self_assignment_only_tells_the_admins(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident()

    await client.post(
        f"{URL}/{inc['key']}/assign",
        json={"assignee_id": str(people["mira"].id)},
        headers=people["mira"].headers,
    )

    # Mira is not told about her own action; the team's admin still is.
    assert await emails(db) == [("Ada Admin", K.INCIDENT_ASSIGNED)]
    assert await in_app(db) == [("Ada Admin", K.INCIDENT_ASSIGNED)]


async def test_opted_out_user_gets_in_app_but_no_email(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    await client.patch(
        f"/api/v1/users/{people['max'].id}",
        json={"notify_email": False},
        headers=people["max"].headers,
    )

    await create_incident(assignee_id=str(people["max"].id))

    assert await emails(db) == [("Ada Admin", K.INCIDENT_ASSIGNED)]  # not Max: opted out
    assert await in_app(db) == [
        ("Ada Admin", K.INCIDENT_ASSIGNED),
        ("Max Member", K.INCIDENT_ASSIGNED),
    ]


# ---------------------------------------------------------------- resolution


async def test_resolve_notifies_reporter_watchers_and_admins(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))
    await watch(client, inc["key"], people["sam"])  # viewers may watch
    await clear(db)

    await client.post(
        f"{URL}/{inc['key']}/transition",
        json={"status": "resolved", "note": "Fixed it"},
        headers=people["max"].headers,  # the assignee resolves: not notified themself
    )

    expected = [
        ("Ada Admin", K.INCIDENT_RESOLVED),  # the team's admin hears it was completed
        ("Mira Member", K.INCIDENT_RESOLVED),
        ("Sam Viewer", K.INCIDENT_RESOLVED),
    ]
    assert await emails(db) == expected
    assert await in_app(db) == expected
    async with db() as s:
        body = await s.scalar(select(NotificationOutbox.body_text).limit(1))
    assert body is not None and "Fixed it" in body  # the resolution note travels along


async def test_other_transitions_are_emailed_as_updates(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))
    await clear(db)

    await client.post(
        f"{URL}/{inc['key']}/transition",
        json={"status": "in_progress"},
        headers=people["max"].headers,
    )

    assert await emails(db) == [
        ("Ada Admin", K.INCIDENT_UPDATED),
        ("Mira Member", K.INCIDENT_UPDATED),  # the reporter
    ]
    async with db() as s:
        body = await s.scalar(select(NotificationOutbox.body_text).limit(1))
    assert body is not None and "Status: Open -> In progress" in body


async def test_edits_email_the_assignee_and_admins_once_listing_every_change(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id), priority="low")
    await clear(db)

    res = await client.patch(
        f"{URL}/{inc['key']}",
        json={"priority": "critical", "title": "Checkout is down for everyone"},
        headers=people["mira"].headers,
    )
    assert res.status_code == 200, res.text

    assert await emails(db) == [
        ("Ada Admin", K.INCIDENT_UPDATED),
        ("Max Member", K.INCIDENT_UPDATED),  # the assignee hears about changes to their work
    ]
    async with db() as s:
        body = await s.scalar(select(NotificationOutbox.body_text).limit(1))
    assert body is not None
    assert "Priority: Low -> Critical" in body
    assert "Title: Checkout is down for everyone" in body


async def test_an_edit_that_changes_nothing_sends_nothing(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id), priority="low")
    await clear(db)
    await client.patch(
        f"{URL}/{inc['key']}", json={"priority": "low"}, headers=people["mira"].headers
    )
    assert await emails(db) == [] and await in_app(db) == []


# ---------------------------------------------------------------- adding people


async def test_adding_a_teammate_emails_them_and_they_follow_it(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident()
    await clear(db)
    url = f"{URL}/{inc['key']}/watchers"
    body = {"user_id": str(people["max"].id)}

    res = await client.post(url, json=body, headers=people["admin"].headers)
    assert res.status_code == 200, res.text
    assert str(people["max"].id) in {w["id"] for w in res.json()["watchers"]}
    assert await emails(db) == [("Max Member", K.INCIDENT_ADDED)]

    again = await client.post(url, json=body, headers=people["admin"].headers)
    assert again.status_code == 200
    assert await emails(db) == [("Max Member", K.INCIDENT_ADDED)]  # no second email

    # From now on Max hears about updates like any watcher.
    await client.patch(
        f"{URL}/{inc['key']}", json={"priority": "high"}, headers=people["mira"].headers
    )
    assert ("Max Member", K.INCIDENT_UPDATED) in await emails(db)


async def test_adding_people_rules(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    make_user: MakeUser,
) -> None:
    inc = await create_incident()
    url = f"{URL}/{inc['key']}/watchers"
    max_body = {"user_id": str(people["max"].id)}

    # Only the team's admins add other people: not viewers, not members (even the reporter).
    for who in ("sam", "mira"):
        res = await client.post(url, json=max_body, headers=people[who].headers)
        assert res.status_code == 403, who

    outsider = await make_user("out@example.com", team=False)
    res = await client.post(
        url, json={"user_id": str(outsider.id)}, headers=people["admin"].headers
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "not_team_member"

    # Anyone can still follow a task themself through the same endpoint.
    me = await client.post(
        url, json={"user_id": str(people["mira"].id)}, headers=people["mira"].headers
    )
    assert me.status_code == 200 and me.json()["watching"] is True

    await client.post(url, json=max_body, headers=people["admin"].headers)
    max_url = f"{url}/{people['max'].id}"
    # Taking someone else off is also admin-only; leaving yourself is always allowed.
    assert (await client.delete(max_url, headers=people["mira"].headers)).status_code == 403
    removed = await client.delete(max_url, headers=people["admin"].headers)
    assert removed.status_code == 200
    assert str(people["max"].id) not in {w["id"] for w in removed.json()["watchers"]}
    leave = await client.delete(f"{url}/{people['mira'].id}", headers=people["mira"].headers)
    assert leave.status_code == 200 and leave.json()["watching"] is False


# ---------------------------------------------------------------- comments + mentions


async def test_comment_notifies_participants_and_emails_watchers(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))
    await watch(client, inc["key"], people["admin"])
    await clear(db)

    await client.post(
        f"{URL}/{inc['key']}/comments", json={"body": "Looking now"}, headers=people["max"].headers
    )

    assert await emails(db) == [("Ada Admin", K.INCIDENT_COMMENTED)]
    assert await in_app(db) == [
        ("Ada Admin", K.INCIDENT_COMMENTED),
        ("Mira Member", K.INCIDENT_COMMENTED),
    ]


async def test_mention_emails_the_mentioned_user_instead_of_the_generic_notice(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))
    await clear(db)

    await client.post(
        f"{URL}/{inc['key']}/comments",
        json={"body": "@mira can you confirm? Also ping @ada. Not an email: bob@max.com"},
        headers=people["max"].headers,
    )

    assert await emails(db) == [("Ada Admin", K.MENTIONED), ("Mira Member", K.MENTIONED)]
    assert await in_app(db) == [("Ada Admin", K.MENTIONED), ("Mira Member", K.MENTIONED)]


async def test_internal_notes_never_reach_viewers(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident()
    await watch(client, inc["key"], people["sam"])
    await clear(db)

    await client.post(
        f"{URL}/{inc['key']}/comments",
        json={"body": "Internal: @sam is not told about this", "is_internal": True},
        headers=people["max"].headers,
    )

    names = {name for name, _ in await in_app(db)}
    assert "Sam Viewer" not in names
    assert names == {"Mira Member"}


# ---------------------------------------------------------------- transactional guarantees


async def test_rolled_back_change_leaves_no_notification(
    people: dict[str, Person], create_incident: CreateIncident, db: Db, settings: Settings
) -> None:
    inc = await create_incident()
    await clear(db)

    async with db() as s:
        mira = await s.get(User, people["mira"].id)
        assert mira is not None
        real_commit = s.commit

        async def failing_commit() -> None:
            raise RuntimeError("database went away")

        s.commit = failing_commit  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            await incident_service.assign(s, settings, mira, str(inc["key"]), people["max"].id)
        await s.rollback()
        s.commit = real_commit  # type: ignore[method-assign]

    assert await emails(db) == [] and await in_app(db) == []


async def test_duplicate_delivery_for_one_event_is_impossible(
    people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    await create_incident(assignee_id=str(people["max"].id))
    async with db() as s:
        row = await s.scalar(select(NotificationOutbox))
        assert row is not None
        s.add(
            NotificationOutbox(
                event_id=row.event_id,
                incident_id=row.incident_id,
                recipient_user_id=row.recipient_user_id,
                recipient_email=row.recipient_email,
                kind=row.kind,
                subject="dup",
                body_text="dup",
                body_html="dup",
            )
        )
        with pytest.raises(Exception, match="uq_notification_outbox_event_user_kind"):
            await s.commit()


# ---------------------------------------------------------------- SLA breach checker


async def test_sla_breach_is_flagged_exactly_once(
    people: dict[str, Person], create_incident: CreateIncident, db: Db, settings: Settings
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))
    await clear(db)
    async with db() as s:
        await s.execute(
            update(Incident)
            .where(Incident.id == inc["id"])
            .values(resolution_due_at=utcnow() - timedelta(minutes=5))
        )
        await s.commit()

    async with db() as s:
        first = await sla_checker.check(s, settings)
    async with db() as s:
        second = await sla_checker.check(s, settings)

    assert (first, second) == (1, 0)
    assert await emails(db) == [("Max Member", K.SLA_BREACHED)]  # the assignee
    assert await in_app(db) == [("Ada Admin", K.SLA_BREACHED), ("Max Member", K.SLA_BREACHED)]
    async with db() as s:
        events = await s.scalar(
            select(func.count()).where(IncidentEvent.event_type == EventType.SLA_BREACHED)
        )
    assert events == 1


async def test_new_deadline_can_breach_again(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    db: Db,
    settings: Settings,
) -> None:
    inc = await create_incident(priority="low")
    async with db() as s:
        await s.execute(
            update(Incident)
            .where(Incident.id == inc["id"])
            .values(
                created_at=utcnow() - timedelta(days=5),
                resolution_due_at=utcnow() - timedelta(hours=1),
            )
        )
        await s.commit()
    async with db() as s:
        assert await sla_checker.check(s, settings) == 1

    # A priority change sets a new deadline (from the back-dated creation: also passed).
    await client.patch(
        f"{URL}/{inc['key']}", json={"priority": "critical"}, headers=people["mira"].headers
    )
    async with db() as s:
        assert await sla_checker.check(s, settings) == 1


async def test_unassigned_breach_goes_to_the_reporter_and_resolved_work_is_ignored(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    db: Db,
    settings: Settings,
) -> None:
    open_one = await create_incident(title="Unassigned and late")
    done = await create_incident(title="Resolved and late")
    await client.post(
        f"{URL}/{done['key']}/transition",
        json={"status": "resolved"},
        headers=people["admin"].headers,
    )
    await clear(db)
    async with db() as s:
        await s.execute(update(Incident).values(resolution_due_at=utcnow() - timedelta(minutes=1)))
        await s.commit()

    async with db() as s:
        assert await sla_checker.check(s, settings) == 1

    assert await emails(db) == [("Mira Member", K.SLA_BREACHED)]
    del open_one


# ---------------------------------------------------------------- watchers


async def test_watch_is_idempotent_and_audited(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()

    first = await client.post(f"{URL}/{inc['key']}/watch", headers=people["sam"].headers)
    again = await client.post(f"{URL}/{inc['key']}/watch", headers=people["sam"].headers)
    other_view = await client.get(f"{URL}/{inc['key']}", headers=people["mira"].headers)
    unwatched = await client.delete(f"{URL}/{inc['key']}/watch", headers=people["sam"].headers)
    events = (await client.get(f"{URL}/{inc['key']}/events", headers=people["mira"].headers)).json()

    assert first.json()["watching"] is True and again.json()["watching"] is True
    assert [w["name"] for w in first.json()["watchers"]] == ["Sam Viewer"]
    assert other_view.json()["watching"] is False
    assert unwatched.json()["watching"] is False and unwatched.json()["watchers"] == []
    assert [e["event_type"] for e in events].count("watcher_added") == 1
    assert [e["event_type"] for e in events][-1] == "watcher_removed"


# ---------------------------------------------------------------- notification API


async def test_notification_centre_lists_counts_and_marks_read(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    await create_incident(title="First for Max", assignee_id=str(people["max"].id))
    await create_incident(title="Second for Max", assignee_id=str(people["max"].id))
    h = people["max"].headers

    listing = (await client.get("/api/v1/notifications", headers=h)).json()
    assert listing["unread_count"] == 2
    top = listing["items"][0]
    assert top["title"].endswith("Assigned to you: Second for Max")
    assert top["actor"]["name"] == "Mira Member"
    assert top["incident_key"].startswith("TASK-")

    assert (
        await client.post(f"/api/v1/notifications/{top['id']}/read", headers=h)
    ).status_code == 204
    assert (await client.get("/api/v1/notifications", headers=h)).json()["unread_count"] == 1
    assert (
        (await client.get("/api/v1/notifications", params={"unread": "true"}, headers=h))
        .json()["items"][0]["title"]
        .endswith("First for Max")
    )
    assert (await client.post("/api/v1/notifications/read-all", headers=h)).status_code == 204
    assert (await client.get("/api/v1/notifications", headers=h)).json()["unread_count"] == 0

    # Someone else's notification cannot be touched (404, not 403: no existence leak).
    assert (
        await client.post(f"/api/v1/notifications/{top['id']}/read", headers=people["mira"].headers)
    ).status_code == 404


async def test_my_email_log(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    await create_incident(assignee_id=str(people["max"].id))

    log_ = (await client.get("/api/v1/notifications/emails", headers=people["max"].headers)).json()
    others = (
        await client.get("/api/v1/notifications/emails", headers=people["mira"].headers)
    ).json()

    assert [(e["kind"], e["status"]) for e in log_] == [("incident_assigned", "pending")]
    assert others == []


# ---------------------------------------------------------------- admin outbox


async def test_admin_outbox_and_retry(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    await create_incident(assignee_id=str(people["max"].id))
    async with db() as s:
        row = await s.scalar(select(NotificationOutbox))
        assert row is not None
        row.status, row.attempts, row.last_error = (
            OutboxStatus.FAILED,
            5,
            "smtp: connection refused",
        )
        await s.commit()
        row_id = row.id

    assert (
        await client.get("/api/v1/admin/outbox", headers=people["mira"].headers)
    ).status_code == 403
    page = (
        await client.get(
            "/api/v1/admin/outbox", params={"status": "failed"}, headers=people["admin"].headers
        )
    ).json()
    # Max's email failed; the admin's own copy of the assignment is still pending.
    assert page["counts"] == {"pending": 1, "sent": 0, "failed": 1}
    assert page["items"][0]["last_error"] == "smtp: connection refused"
    assert page["worker"]["status"] == "unknown"

    retry = await client.post(
        f"/api/v1/admin/outbox/{row_id}/retry", headers=people["admin"].headers
    )
    again = await client.post(
        f"/api/v1/admin/outbox/{row_id}/retry", headers=people["admin"].headers
    )

    assert retry.status_code == 204
    assert again.status_code == 409  # already pending
    async with db() as s:
        fresh = await s.get(NotificationOutbox, row_id)
        assert fresh is not None
        assert (fresh.status, fresh.attempts) == (OutboxStatus.PENDING, 0)


# ---------------------------------------------------------------- several assignees


async def test_several_assignees_each_get_the_assignment_email(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident()
    await clear(db)
    url = f"{URL}/{inc['key']}/assignees"
    both = [str(people["max"].id), str(people["mira"].id)]

    res = await client.put(url, json={"user_ids": both}, headers=people["mira"].headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [a["name"] for a in body["assignees"]] == ["Max Member", "Mira Member"]
    assert body["assignee"]["name"] == "Max Member"  # the first is the lead

    # Max is emailed; Mira assigned herself too, so she is not; the admin gets a copy.
    assert await emails(db) == [
        ("Ada Admin", K.INCIDENT_ASSIGNED),
        ("Max Member", K.INCIDENT_ASSIGNED),
    ]
    async with db() as s:
        admin_copy = await s.scalar(
            select(NotificationOutbox.subject)
            .join(User, User.id == NotificationOutbox.recipient_user_id)
            .where(User.name == "Ada Admin")
        )
    assert admin_copy is not None
    assert "Assigned to Max Member and Mira Member" in admin_copy  # not "to you"

    # Setting the same list again changes nothing and emails nobody.
    await clear(db)
    again = await client.put(url, json={"user_ids": both}, headers=people["mira"].headers)
    assert again.status_code == 200
    assert await emails(db) == []


async def test_every_assignee_hears_about_updates_and_can_edit(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    inc = await create_incident(by="admin")
    url = f"{URL}/{inc['key']}"
    await client.put(
        f"{url}/assignees",
        json={"user_ids": [str(people["mira"].id), str(people["max"].id)]},
        headers=people["admin"].headers,
    )
    await clear(db)

    # Max is the second assignee, not the lead: he may still edit the task.
    res = await client.patch(url, json={"priority": "high"}, headers=people["max"].headers)
    assert res.status_code == 200, res.text
    assert ("Mira Member", K.INCIDENT_UPDATED) in await emails(db)  # the lead hears it

    mine = await client.get(URL, params={"assignee": "me"}, headers=people["max"].headers)
    assert [i["key"] for i in mine.json()["items"]] == [inc["key"]]  # "My work" too


async def test_assignee_list_rules(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))
    url = f"{URL}/{inc['key']}"

    viewer_assignee = await client.put(
        f"{url}/assignees",
        json={"user_ids": [str(people["max"].id), str(people["sam"].id)]},
        headers=people["mira"].headers,
    )
    assert viewer_assignee.status_code == 422  # viewers cannot be assigned

    by_viewer = await client.put(
        f"{url}/assignees", json={"user_ids": []}, headers=people["sam"].headers
    )
    assert by_viewer.status_code == 403

    await client.post(
        f"{url}/transition", json={"status": "in_progress"}, headers=people["max"].headers
    )
    emptied = await client.put(
        f"{url}/assignees", json={"user_ids": []}, headers=people["mira"].headers
    )
    assert emptied.status_code == 409  # work in progress needs someone on it

    too_many = await client.put(
        f"{url}/assignees",
        json={"user_ids": [str(people["max"].id)] * 11},
        headers=people["mira"].headers,
    )
    assert too_many.status_code == 422

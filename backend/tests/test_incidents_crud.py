"""Incidents: create, read (UUID or TASK-key), update (audited), assign, soft delete."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import httpx
import pytest

from tests.conftest import CreateIncident, Person

pytestmark = pytest.mark.db

URL = "/api/v1/incidents"


async def _events(client: httpx.AsyncClient, key: object, who: Person) -> list[dict[str, object]]:
    res = await client.get(f"{URL}/{key}/events", headers=who.headers)
    assert res.status_code == 200, res.text
    return list(res.json())


# ---------------------------------------------------------------- create


async def test_create_sets_reporter_key_sla_and_audit(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    res = await client.post(
        URL,
        json={
            "title": "  Checkout returns 500  ",
            "description": "Since the **14:02** deploy",
            "priority": "critical",
            "category": "payments",
            "tags": ["API", "api", "checkout"],
        },
        headers=people["mira"].headers,
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["key"] == f"TASK-{body['number']}"
    assert body["title"] == "Checkout returns 500"
    assert body["status"] == "open"
    assert body["tags"] == ["api", "checkout"]  # lower-cased and de-duplicated
    assert body["reporter"]["id"] == str(people["mira"].id)
    assert body["assignee"] is None
    created = datetime.fromisoformat(body["created_at"])
    assert datetime.fromisoformat(body["response_due_at"]) - created == timedelta(minutes=30)
    assert datetime.fromisoformat(body["resolution_due_at"]) - created == timedelta(hours=4)
    assert body["allowed_transitions"] == ["resolved"]  # reporter, unassigned
    assert body["permissions"] == {
        "can_edit": True,
        "can_assign": True,
        "can_comment": True,
        "can_delete": True,  # Mira created it
    }

    events = await _events(client, body["key"], people["mira"])
    assert [e["event_type"] for e in events] == ["created"]


async def test_create_with_assignee_counts_as_first_response(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident(assignee_id=str(people["max"].id))

    assert body["assignee"]["name"] == "Max Member"  # type: ignore[index]
    assert body["first_response_at"] is not None
    events = await _events(client, body["key"], people["mira"])
    assert [e["event_type"] for e in events] == ["created", "assigned"]


async def test_viewer_cannot_create(client: httpx.AsyncClient, people: dict[str, Person]) -> None:
    res = await client.post(URL, json={"title": "Nope nope"}, headers=people["sam"].headers)

    assert res.status_code == 403


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "ab"}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"title": "Valid title", "priority": "urgent"}, "priority"),
        ({"title": "Valid title", "tags": ["has space"]}, "tags"),
        ({"title": "Valid title", "tags": [f"t{i}" for i in range(11)]}, "tags"),
        ({"title": "Valid title", "assignee_id": "not-a-uuid"}, "assignee_id"),
        ({"title": "Valid title", "status": "closed"}, "status"),  # unknown field
    ],
)
async def test_create_validation(
    client: httpx.AsyncClient, people: dict[str, Person], payload: dict[str, object], field: str
) -> None:
    res = await client.post(URL, json=payload, headers=people["mira"].headers)

    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"]["fields"][0]["loc"][:2] == ["body", field]
    assert err["request_id"] == res.headers["x-request-id"]


@pytest.mark.parametrize("who", ["unknown", "sam"])
async def test_assignee_must_be_an_active_worker(
    client: httpx.AsyncClient, people: dict[str, Person], who: str
) -> None:
    assignee = uuid.uuid4() if who == "unknown" else people[who].id
    res = await client.post(
        URL,
        json={"title": "Valid title", "assignee_id": str(assignee)},
        headers=people["mira"].headers,
    )

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_assignee"


async def test_idempotency_key_prevents_duplicates(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    headers = {**people["mira"].headers, "Idempotency-Key": "retry-7f3a"}
    first = await client.post(URL, json={"title": "Flaky network"}, headers=headers)
    retry = await client.post(URL, json={"title": "Flaky network"}, headers=headers)

    assert first.status_code == retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]
    assert retry.headers["idempotent-replayed"] == "true"
    listing = await client.get(URL, headers=people["mira"].headers)
    assert listing.json()["total"] == 1


# ---------------------------------------------------------------- read


async def test_get_by_uuid_key_or_number(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident()

    for ident in (body["id"], body["key"], str(body["key"]).lower(), body["number"]):
        res = await client.get(f"{URL}/{ident}", headers=people["sam"].headers)
        assert res.status_code == 200, ident
        assert res.json()["id"] == body["id"]


@pytest.mark.parametrize("ident", ["TASK-99999", str(uuid.uuid4()), "garbage"])
async def test_unknown_incident_is_404(
    client: httpx.AsyncClient, people: dict[str, Person], ident: str
) -> None:
    res = await client.get(f"{URL}/{ident}", headers=people["mira"].headers)

    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_requires_authentication(client: httpx.AsyncClient, db: object) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json={"title": "abc"})).status_code == 401


# ---------------------------------------------------------------- update


async def test_update_audits_each_changed_field(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident(description="old", category="db")

    res = await client.patch(
        f"{URL}/{body['key']}",
        json={"title": "Database pool exhausted (prod)", "description": "new", "category": "db"},
        headers=people["mira"].headers,
    )

    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Database pool exhausted (prod)"
    updates = [
        e
        for e in await _events(client, body["key"], people["mira"])
        if e["event_type"] == "updated"
    ]
    assert {(e["field"], e["old_value"], e["new_value"]) for e in updates} == {
        ("title", "Database connection pool exhausted", "Database pool exhausted (prod)"),
        ("description", "old", "new"),
    }  # category unchanged -> no event
    assert all(e["actor"]["id"] == str(people["mira"].id) for e in updates)  # type: ignore[index]


async def test_priority_change_recomputes_resolution_due(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident(priority="low")

    res = await client.patch(
        f"{URL}/{body['key']}", json={"priority": "critical"}, headers=people["mira"].headers
    )

    created = datetime.fromisoformat(res.json()["created_at"])
    assert datetime.fromisoformat(res.json()["resolution_due_at"]) - created == timedelta(hours=4)
    events = await _events(client, body["key"], people["mira"])
    event = next(e for e in events if e["event_type"] == "priority_changed")
    assert event["old_value"]["priority"] == "low"  # type: ignore[index]
    assert event["new_value"]["priority"] == "critical"  # type: ignore[index]


@pytest.mark.parametrize(("who", "expected"), [("max", 403), ("sam", 403), ("admin", 200)])
async def test_only_reporter_assignee_or_admin_can_edit(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    who: str,
    expected: int,
) -> None:
    body = await create_incident()

    res = await client.patch(
        f"{URL}/{body['key']}", json={"title": "Edited title"}, headers=people[who].headers
    )

    assert res.status_code == expected


async def test_null_title_is_rejected(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident()

    res = await client.patch(
        f"{URL}/{body['key']}", json={"title": None}, headers=people["mira"].headers
    )

    assert res.status_code == 422


# ---------------------------------------------------------------- assignment


async def test_assign_reassign_unassign_are_audited(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident()
    url = f"{URL}/{body['key']}/assign"
    h = people["mira"].headers

    first = await client.post(url, json={"assignee_id": str(people["max"].id)}, headers=h)
    again = await client.post(url, json={"assignee_id": str(people["max"].id)}, headers=h)  # no-op
    second = await client.post(url, json={"assignee_id": str(people["admin"].id)}, headers=h)
    cleared = await client.post(url, json={"assignee_id": None}, headers=h)

    assert first.json()["assignee"]["name"] == "Max Member"
    assert first.json()["first_response_at"] is not None
    assert again.status_code == second.status_code == cleared.status_code == 200
    assert cleared.json()["assignee"] is None
    events = [
        e for e in await _events(client, body["key"], people["mira"]) if e["field"] == "assignee"
    ]
    assert [
        (e["event_type"], (e["old_value"] or {}).get("name"), (e["new_value"] or {}).get("name"))
        for e in events
    ] == [
        ("assigned", None, "Max Member"),
        ("assigned", "Max Member", "Ada Admin"),
        ("unassigned", "Ada Admin", None),
    ]


async def test_viewer_cannot_assign(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident()

    res = await client.post(
        f"{URL}/{body['key']}/assign",
        json={"assignee_id": str(people["max"].id)},
        headers=people["sam"].headers,
    )

    assert res.status_code == 403


# ---------------------------------------------------------------- soft delete


async def test_soft_delete_and_restore(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident()
    url = f"{URL}/{body['key']}"

    # Max did not create it and is not an admin; Sam is a viewer.
    assert (await client.delete(url, headers=people["max"].headers)).status_code == 403
    assert (await client.delete(url, headers=people["sam"].headers)).status_code == 403
    assert (await client.delete(url, headers=people["admin"].headers)).status_code == 204

    assert (await client.get(url, headers=people["mira"].headers)).status_code == 404
    assert (await client.get(URL, headers=people["mira"].headers)).json()["total"] == 0
    admin_view = await client.get(url, headers=people["admin"].headers)
    assert admin_view.status_code == 200 and admin_view.json()["is_deleted"] is True
    assert admin_view.json()["allowed_transitions"] == []
    bin_ = await client.get(URL, params={"deleted": "true"}, headers=people["admin"].headers)
    assert bin_.json()["total"] == 1
    assert (
        await client.get(URL, params={"deleted": "true"}, headers=people["mira"].headers)
    ).status_code == 422
    # deleted incidents are read-only, even for admins
    assert (
        await client.patch(url, json={"title": "Zombie edit"}, headers=people["admin"].headers)
    ).status_code == 404

    restored = await client.post(f"{url}/restore", headers=people["admin"].headers)
    assert restored.status_code == 200 and restored.json()["is_deleted"] is False
    types = [e["event_type"] for e in await _events(client, body["key"], people["admin"])]
    assert types[-2:] == ["deleted", "restored"]


async def test_old_inc_keys_still_open_the_task(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    """Keys read TASK-7 since the rename; links and bookmarks with INC-7 keep working."""
    created = await client.post(
        URL, json={"title": "Renamed key check"}, headers=people["mira"].headers
    )
    key = created.json()["key"]
    number = key.removeprefix("TASK-")
    assert key.startswith("TASK-")
    for ident in (key, f"INC-{number}", f"inc-{number}", number):
        res = await client.get(f"{URL}/{ident}", headers=people["mira"].headers)
        assert res.status_code == 200, ident
        assert res.json()["key"] == key
    found = await client.get(URL, params={"q": f"INC-{number}"}, headers=people["mira"].headers)
    assert [i["key"] for i in found.json()["items"]] == [key]


async def test_task_shows_who_created_it_and_who_assigned_it(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    created = await client.post(
        URL, json={"title": "Who did what check"}, headers=people["mira"].headers
    )
    key = created.json()["key"]
    assert created.json()["reporter"]["name"] == "Mira Member"  # "Created by"
    assert created.json()["assigned_by"] is None  # nobody assigned yet

    await client.put(
        f"{URL}/{key}/assignees",
        json={"user_ids": [str(people["max"].id), str(people["mira"].id)]},
        headers=people["admin"].headers,
    )
    task = (await client.get(f"{URL}/{key}", headers=people["mira"].headers)).json()
    assert [a["name"] for a in task["assignees"]] == ["Max Member", "Mira Member"]
    assert task["assigned_by"]["name"] == "Ada Admin"  # who did the assigning


async def test_the_creator_can_delete_their_task_but_only_admins_restore(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    body = await create_incident()  # created by Mira (a member)
    url = f"{URL}/{body['key']}"
    seen_by = {
        who: (await client.get(url, headers=people[who].headers)).json()["permissions"][
            "can_delete"
        ]
        for who in ("mira", "admin", "max", "sam")
    }
    assert seen_by == {"mira": True, "admin": True, "max": False, "sam": False}

    assert (await client.delete(url, headers=people["mira"].headers)).status_code == 204
    # Restoring is for the admins' recycle bin; the creator can no longer even see it.
    assert (await client.post(f"{url}/restore", headers=people["mira"].headers)).status_code in (
        403,
        404,
    )
    restored = await client.post(f"{url}/restore", headers=people["admin"].headers)
    assert restored.status_code == 200

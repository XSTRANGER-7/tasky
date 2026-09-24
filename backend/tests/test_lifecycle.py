"""The server-side state machine over HTTP: every valid move, every invalid one (409),
permission failures (403) and the assignee rule (422), with timestamps and audit rows."""

from __future__ import annotations

import httpx
import pytest

from app.models import Status
from app.services.permissions import ALLOWED
from tests.conftest import CreateIncident, Person

pytestmark = pytest.mark.db

URL = "/api/v1/incidents"


async def _move(
    client: httpx.AsyncClient, key: object, to: str, who: Person, note: str | None = None
) -> httpx.Response:
    body = {"status": to} if note is None else {"status": to, "note": note}
    return await client.post(f"{URL}/{key}/transition", json=body, headers=who.headers)


async def _at(
    client: httpx.AsyncClient, people: dict[str, Person], create: CreateIncident, status: str
) -> dict[str, object]:
    """An incident (reporter mira, assignee max) driven by the admin into ``status``."""
    inc = await create(assignee_id=str(people["max"].id))
    path = {
        "open": [],
        "in_progress": ["in_progress"],
        "resolved": ["resolved"],
        "closed": ["resolved", "closed"],
    }[status]
    for step in path:
        assert (await _move(client, inc["key"], step, people["admin"])).status_code == 200
    return inc


VALID = [(frm.value, to.value) for frm, tos in ALLOWED.items() for to in tos]
INVALID = [(frm.value, to.value) for frm in Status for to in Status if to not in ALLOWED[frm]]


@pytest.mark.parametrize(("frm", "to"), VALID)
async def test_every_valid_transition_succeeds(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    frm: str,
    to: str,
) -> None:
    inc = await _at(client, people, create_incident, frm)

    res = await _move(client, inc["key"], to, people["admin"], note="because")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == to
    assert (body["resolved_at"] is not None) == (to in ("resolved", "closed"))
    assert (body["closed_at"] is not None) == (to == "closed")
    events = (
        await client.get(f"{URL}/{inc['key']}/events", headers=people["admin"].headers)
    ).json()
    last = events[-1]
    assert (last["event_type"], last["old_value"], last["new_value"], last["note"]) == (
        "status_changed",
        frm,
        to,
        "because",
    )


@pytest.mark.parametrize(("frm", "to"), INVALID)
async def test_every_invalid_transition_is_409(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    frm: str,
    to: str,
) -> None:
    inc = await _at(client, people, create_incident, frm)

    res = await _move(client, inc["key"], to, people["admin"])

    assert res.status_code == 409, res.text
    err = res.json()["error"]
    assert err["code"] == "invalid_transition"
    assert err["details"]["from"] == frm and err["details"]["to"] == to


async def test_reopen_clears_resolution_timestamps(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await _at(client, people, create_incident, "resolved")

    res = await _move(client, inc["key"], "open", people["mira"])  # the reporter reopens

    assert res.status_code == 200
    assert res.json()["resolved_at"] is None and res.json()["closed_at"] is None


async def test_starting_work_needs_an_assignee(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()

    res = await _move(client, inc["key"], "in_progress", people["admin"])

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "assignee_required"


async def test_cannot_unassign_work_in_progress(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await _at(client, people, create_incident, "in_progress")

    res = await client.post(
        f"{URL}/{inc['key']}/assign", json={"assignee_id": None}, headers=people["admin"].headers
    )

    assert res.status_code == 409


@pytest.mark.parametrize(
    ("status", "to", "who", "expected"),
    [
        ("open", "in_progress", "max", 200),  # assignee starts
        ("open", "in_progress", "mira", 403),  # reporter may not start
        ("open", "resolved", "mira", 200),  # reporter may resolve
        ("open", "resolved", "sam", 403),  # viewer
        ("in_progress", "open", "max", 200),  # assignee pauses
        ("in_progress", "open", "mira", 403),
        ("resolved", "closed", "max", 403),  # close is admin-only
        ("resolved", "closed", "mira", 403),
        ("resolved", "closed", "admin", 200),
        ("resolved", "open", "mira", 200),  # reporter reopens
        ("resolved", "open", "sam", 403),
    ],
)
async def test_transition_permissions(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    status: str,
    to: str,
    who: str,
    expected: int,
) -> None:
    inc = await _at(client, people, create_incident, status)

    res = await _move(client, inc["key"], to, people[who])

    assert res.status_code == expected, res.text


async def test_allowed_transitions_are_personal(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident(assignee_id=str(people["max"].id))

    views = {
        who: (await client.get(f"{URL}/{inc['key']}", headers=people[who].headers)).json()[
            "allowed_transitions"
        ]
        for who in ("admin", "mira", "max", "sam")
    }

    assert views == {
        "admin": ["in_progress", "resolved"],
        "mira": ["resolved"],
        "max": ["in_progress", "resolved"],
        "sam": [],
    }


async def test_closed_is_terminal_and_read_only(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await _at(client, people, create_incident, "closed")

    edit = await client.patch(
        f"{URL}/{inc['key']}", json={"title": "Too late now"}, headers=people["admin"].headers
    )
    detail = (await client.get(f"{URL}/{inc['key']}", headers=people["admin"].headers)).json()

    assert edit.status_code == 403
    assert detail["allowed_transitions"] == []
    assert detail["permissions"]["can_edit"] is False

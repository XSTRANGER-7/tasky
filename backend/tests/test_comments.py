"""Comments: thread, internal notes, 15-minute edit window, audit, first response."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models import Comment
from tests.conftest import CreateIncident, Person

pytestmark = pytest.mark.db

URL = "/api/v1/incidents"


async def _comment(
    client: httpx.AsyncClient,
    key: object,
    who: Person,
    body: str = "Looking into it",
    **extra: object,
) -> httpx.Response:
    return await client.post(
        f"{URL}/{key}/comments", json={"body": body, **extra}, headers=who.headers
    )


async def test_thread_is_ordered_and_counted(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    for who, text in (("mira", "First"), ("max", "Second **bold**"), ("admin", "Third")):
        assert (await _comment(client, inc["key"], people[who], text)).status_code == 201

    thread = (
        await client.get(f"{URL}/{inc['key']}/comments", headers=people["sam"].headers)
    ).json()
    detail = (await client.get(f"{URL}/{inc['key']}", headers=people["sam"].headers)).json()

    assert [c["body"] for c in thread] == ["First", "Second **bold**", "Third"]
    assert thread[1]["author"]["name"] == "Max Member"
    assert detail["comment_count"] == 3


async def test_comment_by_non_reporter_is_first_response(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    await _comment(client, inc["key"], people["mira"])  # the reporter: not a response
    assert (await client.get(f"{URL}/{inc['key']}", headers=people["mira"].headers)).json()[
        "first_response_at"
    ] is None

    await _comment(client, inc["key"], people["max"])

    assert (await client.get(f"{URL}/{inc['key']}", headers=people["mira"].headers)).json()[
        "first_response_at"
    ] is not None


async def test_internal_notes_are_hidden_from_viewers(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    await _comment(client, inc["key"], people["max"], "Public update")
    await _comment(client, inc["key"], people["max"], "Root cause: our bad", is_internal=True)

    def bodies(res: httpx.Response) -> list[str]:
        return [c["body"] for c in res.json()]

    member = await client.get(f"{URL}/{inc['key']}/comments", headers=people["mira"].headers)
    viewer = await client.get(f"{URL}/{inc['key']}/comments", headers=people["sam"].headers)
    viewer_events = await client.get(f"{URL}/{inc['key']}/events", headers=people["sam"].headers)
    viewer_detail = await client.get(f"{URL}/{inc['key']}", headers=people["sam"].headers)

    assert bodies(member) == ["Public update", "Root cause: our bad"]
    assert bodies(viewer) == ["Public update"]
    assert "our bad" not in viewer_events.text
    assert viewer_detail.json()["comment_count"] == 1


async def test_viewers_cannot_comment(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()

    assert (await _comment(client, inc["key"], people["sam"])).status_code == 403


@pytest.mark.parametrize("body", ["", "   ", "x" * 5001])
async def test_comment_validation(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, body: str
) -> None:
    inc = await create_incident()

    assert (await _comment(client, inc["key"], people["mira"], body)).status_code == 422


async def test_author_edits_within_window_and_it_is_audited(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    comment = (await _comment(client, inc["key"], people["max"], "Typo hre")).json()
    assert comment["can_modify"] is True

    res = await client.patch(
        f"/api/v1/comments/{comment['id']}",
        json={"body": "Typo here"},
        headers=people["max"].headers,
    )

    assert res.status_code == 200
    assert res.json()["body"] == "Typo here"
    assert res.json()["edited_at"] is not None
    events = (await client.get(f"{URL}/{inc['key']}/events", headers=people["max"].headers)).json()
    edit = next(e for e in events if e["event_type"] == "comment_edited")
    assert edit["old_value"]["preview"] == "Typo hre"
    assert edit["new_value"]["preview"] == "Typo here"


async def test_edit_window_closes_after_15_minutes_except_for_admins(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    db: async_sessionmaker[AsyncSession],
) -> None:
    inc = await create_incident()
    comment = (await _comment(client, inc["key"], people["max"], "Old words")).json()
    async with db() as s:
        await s.execute(
            update(Comment)
            .where(Comment.id == comment["id"])
            .values(created_at=utcnow() - timedelta(minutes=16))
        )
        await s.commit()
    url = f"/api/v1/comments/{comment['id']}"

    late = await client.patch(url, json={"body": "New words"}, headers=people["max"].headers)
    listed = (
        await client.get(f"{URL}/{inc['key']}/comments", headers=people["max"].headers)
    ).json()
    admin = await client.patch(url, json={"body": "Moderated"}, headers=people["admin"].headers)

    assert late.status_code == 403
    assert late.json()["error"]["code"] == "comment_locked"
    assert listed[0]["can_modify"] is False
    assert admin.status_code == 200


async def test_others_cannot_touch_your_comment(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    comment = (await _comment(client, inc["key"], people["max"])).json()
    url = f"/api/v1/comments/{comment['id']}"

    assert (
        await client.patch(url, json={"body": "Hijack"}, headers=people["mira"].headers)
    ).status_code == 403
    assert (await client.delete(url, headers=people["mira"].headers)).status_code == 403


async def test_delete_hides_the_comment_and_audits_it(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    comment = (await _comment(client, inc["key"], people["max"], "Oops, wrong ticket")).json()

    res = await client.delete(f"/api/v1/comments/{comment['id']}", headers=people["max"].headers)

    assert res.status_code == 204
    assert (
        await client.get(f"{URL}/{inc['key']}/comments", headers=people["max"].headers)
    ).json() == []
    again = await client.delete(f"/api/v1/comments/{comment['id']}", headers=people["max"].headers)
    assert again.status_code == 404
    events = (await client.get(f"{URL}/{inc['key']}/events", headers=people["max"].headers)).json()
    assert events[-1]["event_type"] == "comment_deleted"

"""GET /incidents?watching=true and GET /admin/settings."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import CreateIncident, Person

pytestmark = pytest.mark.db


async def test_watching_filter_lists_only_what_i_watch(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    watched = await create_incident(title="Watched one")
    await create_incident(title="Not watched")
    mira = people["mira"].headers
    assert (
        await client.post(f"/api/v1/incidents/{watched['key']}/watch", headers=mira)
    ).status_code == 200

    mine = (await client.get("/api/v1/incidents?watching=true", headers=mira)).json()
    assert [i["key"] for i in mine["items"]] == [watched["key"]]
    assert mine["total"] == 1

    # Watching is per person: the admin watches nothing.
    admin = (
        await client.get("/api/v1/incidents?watching=true", headers=people["admin"].headers)
    ).json()
    assert admin["items"] == []


async def test_admin_settings_shows_the_effective_configuration(
    client: httpx.AsyncClient, people: dict[str, Person]
) -> None:
    res = await client.get("/api/v1/admin/settings", headers=people["admin"].headers)
    assert res.status_code == 200
    body = res.json()
    assert [s["priority"] for s in body["sla"]] == ["critical", "high", "medium", "low"]
    critical = body["sla"][0]
    assert critical["response_minutes"] < critical["resolution_minutes"]
    assert {f["key"] for f in body["flags"]} >= {"email", "worker_in_api", "metrics", "ai"}
    assert body["worker"]["status"] in {"ok", "stale", "unknown"}
    assert "password" not in res.text.lower() and "secret" not in res.text.lower()


@pytest.mark.parametrize("who", ["mira", "sam"])
async def test_admin_settings_is_admin_only(
    client: httpx.AsyncClient, people: dict[str, Person], who: str
) -> None:
    res = await client.get("/api/v1/admin/settings", headers=people[who].headers)
    assert res.status_code == 403

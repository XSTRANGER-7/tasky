"""GET /incidents: every filter alone and combined, search, sort allow-list, cursors."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models import Incident
from tests.conftest import CreateIncident, Person

pytestmark = pytest.mark.db

URL = "/api/v1/incidents"
Db = async_sessionmaker[AsyncSession]


@pytest.fixture
async def catalogue(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> dict[str, dict[str, object]]:
    """Six incidents with distinct attributes, created oldest -> newest."""
    specs = {
        "db": {
            "title": "Database connection pool exhausted",
            "priority": "critical",
            "category": "database",
            "tags": ["prod", "postgres"],
            "assignee_id": str(people["max"].id),
        },
        "login": {
            "title": "Login page slow for EU users",
            "priority": "high",
            "category": "auth",
            "tags": ["prod"],
            "description": "Latency spikes after the CDN change",
        },
        "typo": {"title": "Printer on floor 3 jammed", "priority": "low", "category": "facilities"},
        "vpn": {
            "title": "VPN drops every hour",
            "priority": "medium",
            "tags": ["network"],
            "assignee_id": str(people["mira"].id),
        },
        "email": {
            "title": "Outbound email delayed",
            "priority": "high",
            "category": "messaging",
            "assignee_id": str(people["max"].id),
        },
        "cert": {"title": "TLS certificate expires soon", "priority": "medium", "by": "max"},
    }
    made = {}
    for name, spec in specs.items():
        by = str(spec.pop("by", "mira"))
        made[name] = await create_incident(by=by, **spec)
    h = people["admin"].headers
    await client.post(
        f"{URL}/{made['db']['key']}/transition", json={"status": "in_progress"}, headers=h
    )
    await client.post(
        f"{URL}/{made['typo']['key']}/transition", json={"status": "resolved"}, headers=h
    )
    # make the email incident breached and the VPN one at risk
    async with db() as s:
        now = utcnow()
        await s.execute(
            update(Incident)
            .where(Incident.id == made["email"]["id"])
            .values(resolution_due_at=now - timedelta(minutes=5))
        )
        await s.execute(
            update(Incident)
            .where(Incident.id == made["vpn"]["id"])
            .values(resolution_due_at=now + timedelta(minutes=30))
        )
        await s.commit()
    return made


async def _titles(client: httpx.AsyncClient, who: Person, **params: object) -> list[str]:
    res = await client.get(URL, params=params, headers=who.headers)
    assert res.status_code == 200, res.text
    return [i["title"] for i in res.json()["items"]]


def _names(catalogue: dict[str, dict[str, object]], *names: str) -> set[str]:
    return {str(catalogue[n]["title"]) for n in names}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "in_progress"}, {"db"}),
        ({"status": ["open", "resolved"]}, {"login", "typo", "vpn", "email", "cert"}),
        ({"priority": "critical"}, {"db"}),
        ({"priority": ["high", "medium"]}, {"login", "vpn", "email", "cert"}),
        ({"assignee": "none"}, {"login", "typo", "cert"}),
        ({"category": "DATABASE"}, {"db"}),
        ({"tag": "prod"}, {"db", "login"}),
        ({"tag": ["prod", "postgres"]}, {"db"}),
        ({"sla": "breached"}, {"email"}),
        ({"sla": "at_risk"}, {"vpn"}),
        ({"status": "open", "priority": "high", "assignee": "none"}, {"login"}),
    ],
)
async def test_filters(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    catalogue: dict[str, dict[str, object]],
    params: dict[str, object],
    expected: set[str],
) -> None:
    assert set(await _titles(client, people["sam"], **params)) == _names(catalogue, *expected)


async def test_me_filters_follow_the_caller(
    client: httpx.AsyncClient, people: dict[str, Person], catalogue: dict[str, dict[str, object]]
) -> None:
    assert set(await _titles(client, people["max"], assignee="me")) == _names(
        catalogue, "db", "email"
    )
    assert set(await _titles(client, people["max"], reporter="me")) == _names(catalogue, "cert")
    assert set(await _titles(client, people["mira"], assignee=["me", "none"])) == _names(
        catalogue, "vpn", "login", "typo", "cert"
    )


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("database", {"db"}),  # full-text on the title
        ("CDN latency", {"login"}),  # full-text on the description
        ("databse", {"db"}),  # typo -> trigram
        ("certif", {"cert"}),  # prefix/substring
        ("100%_", set()),  # LIKE wildcards are escaped
    ],
)
async def test_search(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    catalogue: dict[str, dict[str, object]],
    q: str,
    expected: set[str],
) -> None:
    assert set(await _titles(client, people["sam"], q=q)) == _names(catalogue, *expected)


async def test_search_by_incident_key(
    client: httpx.AsyncClient, people: dict[str, Person], catalogue: dict[str, dict[str, object]]
) -> None:
    key = catalogue["vpn"]["key"]

    assert await _titles(client, people["sam"], q=key) == [catalogue["vpn"]["title"]]


async def test_search_ranks_best_match_first(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident, db: Db
) -> None:
    await create_incident(title="Weekly report mentions a database migration later on")
    await create_incident(title="Database down")

    titles = await _titles(client, people["sam"], q="database down")

    assert titles[0] == "Database down"


async def test_default_sort_is_newest_first_and_total_is_reported(
    client: httpx.AsyncClient, people: dict[str, Person], catalogue: dict[str, dict[str, object]]
) -> None:
    res = await client.get(URL, headers=people["sam"].headers)

    assert res.json()["total"] == 6
    assert res.json()["items"][0]["title"] == catalogue["cert"]["title"]


async def test_sort_by_priority_then_number(
    client: httpx.AsyncClient, people: dict[str, Person], catalogue: dict[str, dict[str, object]]
) -> None:
    items = (
        await client.get(URL, params={"sort": "-priority,number"}, headers=people["sam"].headers)
    ).json()["items"]

    assert [i["priority"] for i in items] == ["critical", "high", "high", "medium", "medium", "low"]
    highs = [i["number"] for i in items if i["priority"] == "high"]
    assert highs == sorted(highs)


@pytest.mark.parametrize("sort", ["title", "-password_hash", "relevance", ",,"])
async def test_sort_allow_list(
    client: httpx.AsyncClient, people: dict[str, Person], db: Db, sort: str
) -> None:
    res = await client.get(URL, params={"sort": sort}, headers=people["sam"].headers)

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_sort"


@pytest.mark.parametrize("sort", ["-created_at", "-priority,created_at", "status,-number"])
async def test_cursor_pages_cover_everything_exactly_once(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    catalogue: dict[str, dict[str, object]],
    sort: str,
) -> None:
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": 2, "sort": sort}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get(URL, params=params, headers=people["sam"].headers)).json()
        seen += [i["id"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            break

    assert pages == 3
    assert len(seen) == len(set(seen)) == 6


async def test_cursor_is_stable_while_rows_are_inserted(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    catalogue: dict[str, dict[str, object]],
    create_incident: CreateIncident,
) -> None:
    first = (await client.get(URL, params={"limit": 3}, headers=people["sam"].headers)).json()
    for n in range(3):  # new incidents land "above" the reader
        await create_incident(title=f"Late arrival number {n}")

    second = (
        await client.get(
            URL, params={"limit": 3, "cursor": first["next_cursor"]}, headers=people["sam"].headers
        )
    ).json()

    ids = [i["id"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 6  # no repeats, nothing skipped
    assert {i["title"] for i in second["items"]}.isdisjoint(
        {f"Late arrival number {n}" for n in range(3)}
    )


@pytest.mark.parametrize("cursor", ["garbage", "eyJzIjpbIngiXSwidiI6WzFdfQ"])
async def test_bad_cursor_is_422(
    client: httpx.AsyncClient, people: dict[str, Person], db: Db, cursor: str
) -> None:
    res = await client.get(URL, params={"cursor": cursor}, headers=people["sam"].headers)

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_cursor"


async def test_cursor_from_another_sort_is_rejected(
    client: httpx.AsyncClient, people: dict[str, Person], catalogue: dict[str, dict[str, object]]
) -> None:
    cursor = (await client.get(URL, params={"limit": 1}, headers=people["sam"].headers)).json()[
        "next_cursor"
    ]

    res = await client.get(
        URL, params={"cursor": cursor, "sort": "priority"}, headers=people["sam"].headers
    )

    assert res.status_code == 422


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"status": "nope"}, {"assignee": "bob"}, {"sla": "x"}]
)
async def test_invalid_query_params(
    client: httpx.AsyncClient, people: dict[str, Person], db: Db, params: dict[str, object]
) -> None:
    assert (await client.get(URL, params=params, headers=people["sam"].headers)).status_code == 422


async def test_list_query_uses_the_index(db: Db, catalogue: dict[str, dict[str, object]]) -> None:
    """Spec exit criterion: EXPLAIN on the default list query uses an index. With a tiny
    table the planner prefers a seq scan, so it is disabled to prove the index applies.
    Fresh statistics for this test's rows keep the plan from depending on whatever an
    earlier autovacuum happened to sample."""
    async with db() as s:
        await s.execute(text("ANALYZE incidents"))
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in await s.execute(
                text(
                    "EXPLAIN SELECT * FROM incidents WHERE NOT is_deleted AND status = 'open' "
                    "AND priority = 'high' ORDER BY created_at DESC LIMIT 26"
                )
            )
        )
    assert "ix_incidents_status_priority_created" in plan, plan

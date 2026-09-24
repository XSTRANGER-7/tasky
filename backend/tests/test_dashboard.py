"""Dashboard summary: counts, SLA, MTTR, trend, activity -- and cache invalidation."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models import Incident
from app.services import dashboard_service
from tests.conftest import CreateIncident, Person

pytestmark = pytest.mark.db

URL = "/api/v1/dashboard/summary"


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    dashboard_service.invalidate()


async def test_summary_matches_seeded_data(
    client: httpx.AsyncClient,
    people: dict[str, Person],
    create_incident: CreateIncident,
    db: async_sessionmaker[AsyncSession],
) -> None:
    h = people["admin"].headers
    a = await create_incident(priority="critical", assignee_id=str(people["max"].id))
    b = await create_incident(priority="high", assignee_id=str(people["max"].id))
    c = await create_incident(priority="low")
    d = await create_incident(priority="medium", assignee_id=str(people["mira"].id))
    await client.post(
        f"/api/v1/incidents/{a['key']}/transition", json={"status": "in_progress"}, headers=h
    )
    await client.post(
        f"/api/v1/incidents/{c['key']}/transition", json={"status": "resolved"}, headers=h
    )
    await client.post(
        f"/api/v1/incidents/{d['key']}/transition", json={"status": "resolved"}, headers=h
    )
    await client.post(
        f"/api/v1/incidents/{d['key']}/transition", json={"status": "closed"}, headers=h
    )
    now = utcnow()
    async with db() as s:
        # b is overdue; c took 3 h and d took 5 h to resolve -> MTTR 4 h
        await s.execute(
            update(Incident)
            .where(Incident.id == b["id"])
            .values(resolution_due_at=now - timedelta(minutes=1))
        )
        await s.execute(
            update(Incident)
            .where(Incident.id == c["id"])
            .values(created_at=now - timedelta(hours=3), resolved_at=now)
        )
        await s.execute(
            update(Incident)
            .where(Incident.id == d["id"])
            .values(created_at=now - timedelta(hours=5), resolved_at=now)
        )
        await s.commit()
    dashboard_service.invalidate()

    res = await client.get(URL, headers=people["sam"].headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["counts"] == {"open": 1, "in_progress": 1, "resolved": 1, "closed": 1}
    assert body["by_priority"] == {"critical": 1, "high": 1, "medium": 0, "low": 0}
    assert [(x["user"]["name"], x["count"]) for x in body["open_by_assignee"]] == [
        ("Max Member", 2)
    ]
    assert body["sla"] == {"breached": 1, "at_risk_next_hour": 0}
    assert body["mttr_hours"] == {"last_7d": 4.0, "last_30d": 4.0}
    assert len(body["trend_14d"]) == 14
    assert sum(p["created"] for p in body["trend_14d"]) == 4
    assert sum(p["resolved"] for p in body["trend_14d"]) == 2  # c and d
    assert body["recent_activity"][0]["incident_key"] == d["key"]
    assert len(body["recent_activity"]) == 10


async def test_empty_dashboard(client: httpx.AsyncClient, people: dict[str, Person]) -> None:
    body = (await client.get(URL, headers=people["sam"].headers)).json()

    assert body["counts"] == {"open": 0, "in_progress": 0, "resolved": 0, "closed": 0}
    assert body["mttr_hours"] == {"last_7d": None, "last_30d": None}
    assert body["recent_activity"] == []
    assert sum(p["created"] for p in body["trend_14d"]) == 0


async def test_cache_is_invalidated_by_incident_writes(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    before = (await client.get(URL, headers=people["sam"].headers)).json()
    cached = (await client.get(URL, headers=people["sam"].headers)).json()
    assert cached["generated_at"] == before["generated_at"]  # served from cache

    await create_incident()
    after = (await client.get(URL, headers=people["sam"].headers)).json()

    assert after["counts"]["open"] == before["counts"]["open"] + 1


async def test_deleted_incidents_are_excluded(
    client: httpx.AsyncClient, people: dict[str, Person], create_incident: CreateIncident
) -> None:
    inc = await create_incident()
    await client.delete(f"/api/v1/incidents/{inc['key']}", headers=people["admin"].headers)

    body = (await client.get(URL, headers=people["sam"].headers)).json()

    assert body["counts"]["open"] == 0
    assert body["recent_activity"] == []


async def test_requires_auth(client: httpx.AsyncClient, db: object) -> None:
    assert (await client.get(URL)).status_code == 401

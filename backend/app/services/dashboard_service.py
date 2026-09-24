"""GET /dashboard/summary. A handful of aggregate queries over one team's incidents,
cached in-process per team for 30 s and invalidated by any write to that team's
incidents (``record_event`` calls :func:`invalidate`) -- cheap, and fresh enough for a
team-sized tool. With several workers each has its own cache; the TTL bounds the
staleness."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.base import utcnow
from app.models import Incident, IncidentAssignee, IncidentEvent, Priority, Status, User
from app.models.incident import key_for
from app.schemas.dashboard import (
    ActivityItem,
    AssigneeCount,
    DashboardSummary,
    Mttr,
    SlaSummary,
    TrendPoint,
)
from app.schemas.user import UserPublic

CACHE_TTL_SECONDS = 30.0
TREND_DAYS = 14
ACTIVITY_LIMIT = 10
OPEN_WORK = (Status.OPEN, Status.IN_PROGRESS)

_cache: dict[uuid.UUID, tuple[float, int, DashboardSummary]] = {}
_versions: dict[uuid.UUID, int] = {}
_global_version = 0


def invalidate(team_id: uuid.UUID | None = None) -> None:
    """Drop one team's cached summary, or every team's when ``team_id`` is None."""
    global _global_version
    if team_id is None:
        _global_version += 1
    else:
        _versions[team_id] = _versions.get(team_id, 0) + 1


def _version_of(team_id: uuid.UUID) -> int:
    return _global_version * 1_000_003 + _versions.get(team_id, 0)


async def summary(
    session: AsyncSession, team_id: uuid.UUID, *, use_cache: bool = True
) -> DashboardSummary:
    now_mono = time.monotonic()
    cached = _cache.get(team_id)
    if use_cache and cached is not None:
        cached_at, version, value = cached
        if version == _version_of(team_id) and now_mono - cached_at < CACHE_TTL_SECONDS:
            return value
    version = _version_of(team_id)
    value = await _compute(session, team_id, utcnow())
    _cache[team_id] = (now_mono, version, value)
    return value


async def _compute(session: AsyncSession, team_id: uuid.UUID, now: datetime) -> DashboardSummary:
    live = and_(Incident.is_deleted.is_(False), Incident.team_id == team_id)
    open_work = Incident.status.in_(OPEN_WORK)

    counts = {s.value: 0 for s in Status}
    for status, n in await session.execute(
        select(Incident.status, func.count()).where(live).group_by(Incident.status)
    ):
        counts[status.value] = int(n)

    by_priority = {p.value: 0 for p in reversed(Priority)}
    for priority, n in await session.execute(
        select(Incident.priority, func.count()).where(live, open_work).group_by(Incident.priority)
    ):
        by_priority[priority.value] = int(n)

    # Open work per person: a task with three assignees counts for each of them.
    assigned = (
        await session.execute(
            select(IncidentAssignee.user_id, func.count())
            .join(Incident, Incident.id == IncidentAssignee.incident_id)
            .where(live, open_work)
            .group_by(IncidentAssignee.user_id)
        )
    ).all()
    unassigned = int(
        await session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(live, open_work, Incident.assignee_id.is_(None))
        )
        or 0
    )
    per_assignee: list[tuple[uuid.UUID | None, int]] = sorted(
        [(uid, int(n)) for uid, n in assigned] + ([(None, unassigned)] if unassigned else []),
        key=lambda row: -row[1],
    )
    user_ids = [uid for uid, _ in per_assignee if uid is not None]
    users = (
        {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()}
        if user_ids
        else {}
    )
    open_by_assignee = [
        AssigneeCount(
            user=UserPublic.model_validate(users[uid]) if uid in users else None, count=int(n)
        )
        for uid, n in per_assignee
    ]

    breached = int(
        await session.scalar(
            select(func.count()).where(live, open_work, Incident.resolution_due_at < now)
        )
        or 0
    )
    at_risk = int(
        await session.scalar(
            select(func.count()).where(
                live,
                open_work,
                Incident.resolution_due_at >= now,
                Incident.resolution_due_at < now + timedelta(hours=1),
            )
        )
        or 0
    )

    async def mttr(days: int) -> float | None:
        seconds = await session.scalar(
            select(
                func.avg(func.extract("epoch", Incident.resolved_at - Incident.created_at))
            ).where(
                live,
                Incident.resolved_at.is_not(None),
                Incident.resolved_at >= now - timedelta(days=days),
            )
        )
        return None if seconds is None else round(float(seconds) / 3600, 1)

    today = now.astimezone(UTC).date()
    start = today - timedelta(days=TREND_DAYS - 1)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    created_day = cast(func.timezone("UTC", Incident.created_at), Date)
    resolved_day = cast(func.timezone("UTC", Incident.resolved_at), Date)
    created_rows = await session.execute(
        select(created_day, func.count())
        .where(live, Incident.created_at >= start_dt)
        .group_by(created_day)
    )
    created: dict[date, int] = {day: int(n) for day, n in created_rows}
    resolved_rows = await session.execute(
        select(resolved_day, func.count())
        .where(live, Incident.resolved_at.is_not(None), Incident.resolved_at >= start_dt)
        .group_by(resolved_day)
    )
    resolved: dict[date, int] = {day: int(n) for day, n in resolved_rows}
    trend = []
    for offset in range(TREND_DAYS):
        day: date = start + timedelta(days=offset)
        trend.append(
            TrendPoint(date=day, created=created.get(day, 0), resolved=resolved.get(day, 0))
        )

    events = (
        await session.execute(
            select(IncidentEvent, Incident.number, Incident.title)
            .join(Incident, Incident.id == IncidentEvent.incident_id)
            .where(live)
            .options(joinedload(IncidentEvent.actor))
            .order_by(IncidentEvent.seq.desc())
            .limit(ACTIVITY_LIMIT)
        )
    ).all()
    activity = [
        ActivityItem(
            id=e.id,
            event_type=e.event_type,
            actor=UserPublic.model_validate(e.actor) if e.actor else None,
            incident_id=e.incident_id,
            incident_key=key_for(number),
            incident_title=title,
            field=e.field,
            old_value=e.old_value,
            new_value=e.new_value,
            created_at=e.created_at,
        )
        for e, number, title in events
    ]

    return DashboardSummary(
        counts=counts,
        by_priority=by_priority,
        open_by_assignee=open_by_assignee,
        sla=SlaSummary(breached=breached, at_risk_next_hour=at_risk),
        mttr_hours=Mttr(last_7d=await mttr(7), last_30d=await mttr(30)),
        trend_14d=trend,
        recent_activity=activity,
        generated_at=now,
    )

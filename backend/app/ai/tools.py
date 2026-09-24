"""The only data the AI can see: two read-only queries (spec 10.2), both confined to
one team -- the AI never sees another team's incidents or people.

No emails, tokens or hashes leave here -- people are described by id, first name and
workload only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, Priority, Role, Status, TeamMembership, TeamRole, User
from app.models.incident import key_for

OPEN_WORK = (Status.OPEN, Status.IN_PROGRESS)
DUPLICATE_THRESHOLD = 0.6


@dataclass(frozen=True)
class Similar:
    id: uuid.UUID
    number: int
    title: str
    status: Status
    priority: Priority
    category: str | None
    assignee_id: uuid.UUID | None
    score: float

    @property
    def key(self) -> str:
        return key_for(self.number)


@dataclass(frozen=True)
class Workload:
    user_id: uuid.UUID
    name: str
    role: Role
    open_count: int


async def find_similar_incidents(
    session: AsyncSession,
    text: str,
    *,
    team_id: uuid.UUID,
    exclude: uuid.UUID | None = None,
    limit: int = 5,
) -> list[Similar]:
    """Closest titles by trigram similarity (whole-title and word-level, whichever is
    higher). Deleted incidents never appear."""
    probe = text.strip()[:200]
    if len(probe) < 3:
        return []
    score = cast(
        func.greatest(
            func.similarity(Incident.title, probe), func.word_similarity(probe, Incident.title)
        ),
        Float,
    ).label("score")
    stmt = (
        select(Incident, score)
        .where(
            Incident.is_deleted.is_(False),
            Incident.team_id == team_id,
            or_(Incident.title.op("%")(probe), Incident.title.op("%>")(probe)),
            *([Incident.id != exclude] if exclude else []),
        )
        .order_by(score.desc(), Incident.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        Similar(
            id=i.id,
            number=i.number,
            title=i.title,
            status=i.status,
            priority=i.priority,
            category=i.category,
            assignee_id=i.assignee_id,
            score=round(float(s), 3),
        )
        for i, s in rows
        if s >= 0.25
    ]


async def get_assignee_workload(session: AsyncSession, team_id: uuid.UUID) -> list[Workload]:
    """Everyone in the team who can be assigned, with their open work in that team,
    least loaded first."""
    open_count = func.count(Incident.id).label("open_count")
    stmt = (
        select(User, TeamMembership.role, open_count)
        .join(
            TeamMembership,
            and_(TeamMembership.user_id == User.id, TeamMembership.team_id == team_id),
        )
        .outerjoin(
            Incident,
            and_(
                Incident.assignee_id == User.id,
                Incident.team_id == team_id,
                Incident.status.in_(OPEN_WORK),
                Incident.is_deleted.is_(False),
            ),
        )
        .where(User.is_active.is_(True), TeamMembership.role != TeamRole.VIEWER)
        .group_by(User.id, TeamMembership.role)
        .order_by(open_count, User.name)
    )
    return [
        Workload(user_id=u.id, name=u.name, role=r.as_role(), open_count=int(c))
        for u, r, c in (await session.execute(stmt)).all()
    ]

"""Team, membership and join-request queries. Persistence only -- no decisions about what
is allowed (that is ``services/team_service.py``)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import (
    Incident,
    JoinRequestStatus,
    Team,
    TeamJoinRequest,
    TeamMembership,
    TeamRole,
    User,
)


async def get_team(session: AsyncSession, team_id: uuid.UUID) -> Team | None:
    return await session.get(Team, team_id)


async def slug_taken(session: AsyncSession, slug: str) -> bool:
    return bool(await session.scalar(select(func.count()).where(Team.slug == slug)))


async def get_membership(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False
) -> TeamMembership | None:
    stmt = select(TeamMembership).where(
        TeamMembership.team_id == team_id, TeamMembership.user_id == user_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    membership: TeamMembership | None = await session.scalar(stmt)
    return membership


async def teams_of_user(
    session: AsyncSession, user_id: uuid.UUID
) -> Sequence[tuple[Team, TeamRole]]:
    stmt = (
        select(Team, TeamMembership.role)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id == user_id)
        .order_by(func.lower(Team.name), Team.id)
    )
    return [(team, role) for team, role in (await session.execute(stmt)).all()]


async def team_ids_of_user(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await session.scalars(
        select(TeamMembership.team_id).where(TeamMembership.user_id == user_id)
    )
    return set(rows.all())


async def member_counts(
    session: AsyncSession, team_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    ids = list(team_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(TeamMembership.team_id, func.count())
        .where(TeamMembership.team_id.in_(ids))
        .group_by(TeamMembership.team_id)
    )
    return {team_id: int(n) for team_id, n in rows}


async def incident_counts(
    session: AsyncSession, team_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    ids = list(team_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(Incident.team_id, func.count())
        .where(Incident.team_id.in_(ids), Incident.is_deleted.is_(False))
        .group_by(Incident.team_id)
    )
    return {team_id: int(n) for team_id, n in rows}


async def members(
    session: AsyncSession, team_id: uuid.UUID, *, include_inactive: bool = False
) -> Sequence[tuple[User, TeamMembership]]:
    stmt = (
        select(User, TeamMembership)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(TeamMembership.team_id == team_id)
        .order_by(func.lower(User.name), User.id)
    )
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    return [(user, membership) for user, membership in (await session.execute(stmt)).all()]


async def roles_in_team(
    session: AsyncSession, team_id: uuid.UUID, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, TeamRole]:
    ids = list(set(user_ids))
    if not ids:
        return {}
    rows = await session.execute(
        select(TeamMembership.user_id, TeamMembership.role).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id.in_(ids)
        )
    )
    return dict(rows.tuples().all())


async def managers(session: AsyncSession, team_id: uuid.UUID) -> Sequence[User]:
    """Active admins of a team: who approves join requests and hears about SLA breaches."""
    stmt = (
        select(User)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(
            TeamMembership.team_id == team_id,
            TeamMembership.role == TeamRole.ADMIN,
            User.is_active.is_(True),
        )
    )
    return (await session.scalars(stmt)).all()


async def count_admins(session: AsyncSession, team_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        TeamMembership.team_id == team_id, TeamMembership.role == TeamRole.ADMIN
    )
    return int(await session.scalar(stmt) or 0)


async def search_teams(session: AsyncSession, q: str | None, *, limit: int = 50) -> Sequence[Team]:
    stmt = select(Team).order_by(func.lower(Team.name), Team.id).limit(limit)
    text = (q or "").strip()
    if text:
        pattern = f"%{text.replace('%', r'\%').replace('_', r'\_')}%"
        stmt = stmt.where(or_(Team.name.ilike(pattern), Team.slug.ilike(pattern)))
    return (await session.scalars(stmt)).all()


async def pending_request(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID
) -> TeamJoinRequest | None:
    stmt = select(TeamJoinRequest).where(
        TeamJoinRequest.team_id == team_id,
        TeamJoinRequest.user_id == user_id,
        TeamJoinRequest.status == JoinRequestStatus.PENDING,
    )
    request: TeamJoinRequest | None = await session.scalar(stmt)
    return request


async def get_request(
    session: AsyncSession, request_id: uuid.UUID, *, for_update: bool = False
) -> TeamJoinRequest | None:
    stmt = (
        select(TeamJoinRequest)
        .where(TeamJoinRequest.id == request_id)
        .options(
            joinedload(TeamJoinRequest.team),
            joinedload(TeamJoinRequest.user),
            joinedload(TeamJoinRequest.decided_by),
        )
    )
    if for_update:
        stmt = stmt.with_for_update(of=TeamJoinRequest)
    request: TeamJoinRequest | None = await session.scalar(stmt)
    return request


async def list_requests(
    session: AsyncSession,
    *,
    team_ids: Iterable[uuid.UUID] | None = None,
    user_id: uuid.UUID | None = None,
    status: JoinRequestStatus | None = None,
    limit: int = 200,
) -> Sequence[TeamJoinRequest]:
    stmt = (
        select(TeamJoinRequest)
        .options(
            joinedload(TeamJoinRequest.team),
            joinedload(TeamJoinRequest.user),
            joinedload(TeamJoinRequest.decided_by),
        )
        .order_by(TeamJoinRequest.created_at.desc(), TeamJoinRequest.id)
        .limit(limit)
    )
    if team_ids is not None:
        stmt = stmt.where(TeamJoinRequest.team_id.in_(list(team_ids)))
    if user_id is not None:
        stmt = stmt.where(TeamJoinRequest.user_id == user_id)
    if status is not None:
        stmt = stmt.where(TeamJoinRequest.status == status)
    return (await session.scalars(stmt)).all()

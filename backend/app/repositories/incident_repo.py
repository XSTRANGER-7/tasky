"""Incident, comment and event queries. Persistence only -- no permission decisions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models import Comment, EventType, IdempotencyKey, Incident, IncidentEvent, User

_WITH_PEOPLE = (
    joinedload(Incident.reporter),
    joinedload(Incident.assignee),
    selectinload(Incident.assignees),
)


async def get_incident(
    session: AsyncSession, ident: uuid.UUID | int, *, for_update: bool = False
) -> Incident | None:
    """By UUID or by human number (``INC-142`` -> 142). Always loads reporter/assignee
    fresh from the database (``populate_existing``) so callers never see stale rows."""
    column = Incident.id if isinstance(ident, uuid.UUID) else Incident.number
    stmt = (
        select(Incident)
        .where(column == ident)
        .options(*_WITH_PEOPLE)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Incident)
    incident: Incident | None = (await session.scalars(stmt)).unique().one_or_none()
    return incident


async def last_assigner(session: AsyncSession, incident_id: uuid.UUID) -> User | None:
    """Who made the most recent assignment ("Assigned by" on the task page)."""
    stmt = (
        select(User)
        .join(IncidentEvent, IncidentEvent.actor_id == User.id)
        .where(
            IncidentEvent.incident_id == incident_id,
            IncidentEvent.event_type == EventType.ASSIGNED,
        )
        .order_by(IncidentEvent.seq.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def comment_counts(
    session: AsyncSession, incident_ids: Sequence[uuid.UUID], *, include_internal: bool
) -> dict[uuid.UUID, int]:
    if not incident_ids:
        return {}
    stmt = (
        select(Comment.incident_id, func.count())
        .where(Comment.incident_id.in_(incident_ids), Comment.is_deleted.is_(False))
        .group_by(Comment.incident_id)
    )
    if not include_internal:
        stmt = stmt.where(Comment.is_internal.is_(False))
    return {row[0]: int(row[1]) for row in await session.execute(stmt)}


async def list_comments(
    session: AsyncSession, incident_id: uuid.UUID, *, include_internal: bool
) -> Sequence[Comment]:
    stmt = (
        select(Comment)
        .where(Comment.incident_id == incident_id, Comment.is_deleted.is_(False))
        .options(joinedload(Comment.author))
        .order_by(Comment.created_at, Comment.id)
    )
    if not include_internal:
        stmt = stmt.where(Comment.is_internal.is_(False))
    return (await session.scalars(stmt)).all()


async def get_comment(session: AsyncSession, comment_id: uuid.UUID) -> Comment | None:
    stmt = (
        select(Comment)
        .where(Comment.id == comment_id, Comment.is_deleted.is_(False))
        .options(joinedload(Comment.author))
        .execution_options(populate_existing=True)
    )
    comment: Comment | None = await session.scalar(stmt)
    return comment


async def list_events(session: AsyncSession, incident_id: uuid.UUID) -> Sequence[IncidentEvent]:
    stmt = (
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .options(joinedload(IncidentEvent.actor))
        .order_by(IncidentEvent.seq)
    )
    return (await session.scalars(stmt)).all()


async def get_idempotent_incident_id(
    session: AsyncSession, user_id: uuid.UUID, key: str
) -> uuid.UUID | None:
    stmt = select(IdempotencyKey.incident_id).where(
        IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
    )
    incident_id: uuid.UUID | None = await session.scalar(stmt)
    return incident_id

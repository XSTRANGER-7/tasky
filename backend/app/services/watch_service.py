"""Watchers: anyone who can see an incident may follow it and be notified about it."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InvalidInput, PermissionDenied
from app.models import EventType, IncidentWatcher, NotificationKind, User
from app.repositories import team_repo, user_repo
from app.services import incident_service, notification_service
from app.services import permissions as perms


async def watchers_for(
    session: AsyncSession, incident_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[User]]:
    """All watchers of several incidents in one query (no N+1 on list pages)."""
    if not incident_ids:
        return {}
    rows = await session.execute(
        select(IncidentWatcher.incident_id, User)
        .join(User, User.id == IncidentWatcher.user_id)
        .where(IncidentWatcher.incident_id.in_(incident_ids))
        .order_by(IncidentWatcher.created_at)
    )
    out: dict[uuid.UUID, list[User]] = defaultdict(list)
    for incident_id, user in rows:
        out[incident_id].append(user)
    return out


async def watch(session: AsyncSession, actor: User, raw_ident: str) -> bool:
    """Start watching. Returns False when already watching (idempotent, no event)."""
    incident = await incident_service.load_live(
        session, incident_service.parse_ident(raw_ident), actor
    )
    result = await session.execute(
        insert(IncidentWatcher)
        .values(incident_id=incident.id, user_id=actor.id)
        .on_conflict_do_nothing()
        .returning(IncidentWatcher.user_id)
    )
    added = result.first() is not None
    if added:
        incident_service.record_event(
            session,
            incident,
            actor,
            EventType.WATCHER_ADDED,
            field="watcher",
            new={"id": str(actor.id), "name": actor.name},
        )
    await session.commit()
    return added


async def unwatch(session: AsyncSession, actor: User, raw_ident: str) -> bool:
    incident = await incident_service.load_live(
        session, incident_service.parse_ident(raw_ident), actor
    )
    result = await session.execute(
        delete(IncidentWatcher)
        .where(IncidentWatcher.incident_id == incident.id, IncidentWatcher.user_id == actor.id)
        .returning(IncidentWatcher.user_id)
    )
    removed = result.first() is not None
    if removed:
        incident_service.record_event(
            session,
            incident,
            actor,
            EventType.WATCHER_REMOVED,
            field="watcher",
            old={"id": str(actor.id), "name": actor.name},
        )
    await session.commit()
    return removed


async def add_person(
    session: AsyncSession, settings: Settings, actor: User, raw_ident: str, user_id: uuid.UUID
) -> bool:
    """Add a teammate to a task: they follow it from now on and get an email saying so.
    Only the team's admins add other people (anyone may follow a task themself). Returns
    False when they were already following it (no second email)."""
    if user_id == actor.id:
        return await watch(session, actor, raw_ident)
    if not perms.is_admin(actor):
        raise PermissionDenied("Only team admins can add people to a task")
    incident = await incident_service.load_live(
        session, incident_service.parse_ident(raw_ident), actor
    )
    person = await user_repo.get_user(session, user_id)
    in_team = await team_repo.get_membership(session, incident.team_id, user_id)
    if person is None or not person.is_active or in_team is None:
        raise InvalidInput(
            "Only active members of this team can be added",
            code="not_team_member",
            details={"fields": [{"loc": ["body", "user_id"], "message": "Not in this team"}]},
        )
    result = await session.execute(
        insert(IncidentWatcher)
        .values(incident_id=incident.id, user_id=person.id)
        .on_conflict_do_nothing()
        .returning(IncidentWatcher.user_id)
    )
    added = result.first() is not None
    if added:
        event = incident_service.record_event(
            session,
            incident,
            actor,
            EventType.WATCHER_ADDED,
            field="watcher",
            new={"id": str(person.id), "name": person.name},
        )
        await notification_service.notify(
            session,
            settings,
            NotificationKind.INCIDENT_ADDED,
            incident,
            event,
            actor=actor,
            added=[person],
        )
    await session.commit()
    return added


async def remove_person(
    session: AsyncSession, actor: User, raw_ident: str, user_id: uuid.UUID
) -> bool:
    """Take someone off a task: yourself always; others only as a team admin."""
    if user_id == actor.id:
        return await unwatch(session, actor, raw_ident)
    incident = await incident_service.load_live(
        session, incident_service.parse_ident(raw_ident), actor
    )
    if not perms.is_admin(actor):
        raise PermissionDenied("Only team admins can remove people from a task")
    person = await user_repo.get_user(session, user_id)
    result = await session.execute(
        delete(IncidentWatcher)
        .where(IncidentWatcher.incident_id == incident.id, IncidentWatcher.user_id == user_id)
        .returning(IncidentWatcher.user_id)
    )
    removed = result.first() is not None
    if removed and person is not None:
        incident_service.record_event(
            session,
            incident,
            actor,
            EventType.WATCHER_REMOVED,
            field="watcher",
            old={"id": str(person.id), "name": person.name},
        )
    await session.commit()
    return removed

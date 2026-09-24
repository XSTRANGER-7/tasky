"""Incident use cases: create, read, update, assign, transition, delete, restore.

Every mutation: check permission -> apply -> write ``incident_events`` rows -> commit,
all in one transaction. Because the rules live here (not in routers), a new endpoint
cannot bypass them, and Phase 4 adds notification enqueueing in the same transaction.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, InvalidInput, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    EventType,
    IdempotencyKey,
    Incident,
    IncidentAssignee,
    IncidentEvent,
    NotificationKind,
    Priority,
    Role,
    Status,
    User,
)
from app.models.incident import KEY_PATTERN, key_for
from app.realtime import publish as realtime
from app.repositories import incident_repo, team_repo, user_repo
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.services import dashboard_service, notification_service
from app.services import permissions as perms
from app.services.team_scope import team_id_of

log = get_logger(__name__)

_KEY = re.compile(rf"^{KEY_PATTERN}$", re.IGNORECASE)
AT_RISK_WINDOW = timedelta(hours=1)


class InvalidTransition(AppError):
    status_code = 409
    code = "invalid_transition"


# ---------------------------------------------------------------- helpers


def parse_ident(raw: str) -> uuid.UUID | int:
    """``INC-142``, ``142`` or a UUID."""
    match = _KEY.match(raw.strip())
    if match:
        return int(match.group(1))
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise NotFound("Task not found") from exc


def compute_due(
    created_at: datetime, priority: Priority, settings: Settings
) -> tuple[datetime, datetime]:
    response, resolution = settings.sla_minutes(priority.value)
    return created_at + timedelta(minutes=response), created_at + timedelta(minutes=resolution)


def _user_ref(user: User | None) -> dict[str, str] | None:
    return None if user is None else {"id": str(user.id), "name": user.name}


def _json(value: Any) -> Any:
    if isinstance(value, Status | Priority):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    if isinstance(raw, list):
        return ", ".join(str(v) for v in raw) or "none"
    return str(raw or "none").replace("_", " ")


def describe_change(name: str, old: Any, new: Any) -> str:
    """One line for the "incident updated" email: what changed, from what to what."""
    field = name.replace("_", " ").capitalize()
    if name == "description":
        return "Description was edited"
    if name == "title":
        return f"Title: {new}"
    return f"{field}: {_label(old).capitalize()} -> {_label(new).capitalize()}"


def record_event(
    session: AsyncSession,
    incident: Incident,
    actor: User | None,
    event_type: EventType,
    *,
    field: str | None = None,
    old: Any = None,
    new: Any = None,
    note: str | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        id=uuid.uuid4(),  # known before flush, so notifications can reference it
        incident_id=incident.id,
        actor_id=actor.id if actor else None,
        event_type=event_type,
        field=field,
        old_value=_json(old),
        new_value=_json(new),
        note=note,
    )
    session.add(event)
    dashboard_service.invalidate(incident.team_id)  # every audited write changes it
    realtime.queue(
        session,
        {
            "type": "incident.created" if event_type == EventType.CREATED else "incident.updated",
            "incident": key_for(incident.number),
            "team": str(incident.team_id),
        },
    )
    return event


async def load(
    session: AsyncSession, ident: uuid.UUID | int, actor: User, *, for_update: bool = False
) -> Incident:
    incident = await incident_repo.get_incident(session, ident, for_update=for_update)
    # Another team's incident is indistinguishable from a missing one (no existence leak).
    if (
        incident is None
        or incident.team_id != team_id_of(actor)
        or (incident.is_deleted and not perms.is_admin(actor))
    ):
        raise NotFound("Task not found")
    return incident


async def load_live(session: AsyncSession, ident: uuid.UUID | int, actor: User) -> Incident:
    """Load for mutation: row-locked, and deleted incidents are read-only for everyone."""
    incident = await load(session, ident, actor, for_update=True)
    if incident.is_deleted:
        raise NotFound("Task not found")
    return incident


async def _validate_assignee(session: AsyncSession, actor: User, assignee_id: uuid.UUID) -> User:
    """An assignee must be an active member of the active team who is not a viewer."""
    user = await user_repo.get_user(session, assignee_id)
    team_role = (await team_repo.roles_in_team(session, team_id_of(actor), [assignee_id])).get(
        assignee_id
    )
    if user is None or not user.is_active or team_role is None:
        raise InvalidInput(
            "You can only assign tasks to active members of this team",
            code="invalid_assignee",
            details={
                "fields": [
                    {
                        "loc": ["body", "assignee_id"],
                        "message": "Unknown, inactive, or not in this team",
                    }
                ]
            },
        )
    if team_role.as_role() == Role.VIEWER:
        raise InvalidInput(
            "Viewers cannot be assigned tasks",
            code="invalid_assignee",
            details={
                "fields": [{"loc": ["body", "assignee_id"], "message": "Viewers are read-only"}]
            },
        )
    return user


def _mark_first_response(incident: Incident, now: datetime) -> None:
    if incident.first_response_at is None:
        incident.first_response_at = now


# ---------------------------------------------------------------- reads


async def get(session: AsyncSession, actor: User, raw_ident: str) -> Incident:
    return await load(session, parse_ident(raw_ident), actor)


# ---------------------------------------------------------------- create


async def create(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    data: IncidentCreate,
    *,
    idempotency_key: str | None = None,
) -> tuple[Incident, bool]:
    """Returns (incident, created). A repeated Idempotency-Key returns the original."""
    if not perms.can_create(actor):
        raise PermissionDenied("Viewers cannot create tasks")

    if idempotency_key:
        existing = await incident_repo.get_idempotent_incident_id(
            session, actor.id, idempotency_key
        )
        if existing:
            return await load(session, existing, actor), False

    wanted = _unique(data.assignee_ids or ([data.assignee_id] if data.assignee_id else []))
    team = [await _validate_assignee(session, actor, uid) for uid in wanted]
    assignee = team[0] if team else None
    now = utcnow()
    response_due, resolution_due = compute_due(now, data.priority, settings)
    incident = Incident(
        team_id=team_id_of(actor),
        title=data.title,
        description=data.description,
        priority=data.priority,
        category=data.category,
        tags=data.tags,
        reporter_id=actor.id,
        assignee_id=assignee.id if assignee else None,
        created_at=now,
        updated_at=now,
        response_due_at=response_due,
        resolution_due_at=resolution_due,
        # Spec: the first assignment (or first comment by a non-reporter) is the response.
        first_response_at=now if assignee else None,
    )
    # Set the relationships too, so notification recipients can be resolved before reload.
    incident.reporter = actor
    incident.assignee = assignee
    session.add(incident)
    await session.flush()  # number + id

    record_event(
        session,
        incident,
        actor,
        EventType.CREATED,
        new={"title": incident.title, "priority": incident.priority.value},
    )
    if team:
        _write_assignees(session, incident.id, [u.id for u in team])
        await session.flush()
        assigned = None
        for person in team:
            assigned = record_event(
                session,
                incident,
                actor,
                EventType.ASSIGNED,
                field="assignee",
                new=_user_ref(person),
            )
        assert assigned is not None  # noqa: S101 - team is not empty
        await notification_service.notify(
            session,
            settings,
            NotificationKind.INCIDENT_ASSIGNED,
            incident,
            assigned,
            actor=actor,
            assigned=team,
        )
    if idempotency_key:
        session.add(IdempotencyKey(user_id=actor.id, key=idempotency_key, incident_id=incident.id))

    try:
        await session.commit()
    except IntegrityError:
        # A concurrent retry with the same key won the race: return its incident.
        await session.rollback()
        if idempotency_key:
            existing = await incident_repo.get_idempotent_incident_id(
                session, actor.id, idempotency_key
            )
            if existing:
                return await load(session, existing, actor), False
        raise
    log.info("incident_created", incident=incident.key, by=str(actor.id))
    return await load(session, incident.id, actor), True


# ---------------------------------------------------------------- update


async def update(
    session: AsyncSession, settings: Settings, actor: User, raw_ident: str, changes: IncidentUpdate
) -> Incident:
    incident = await load_live(session, parse_ident(raw_ident), actor)
    if not perms.can_edit(actor, incident):
        raise PermissionDenied("Only the reporter, the assignee or an admin can edit this task")

    fields = changes.model_dump(exclude_unset=True)
    nulls = sorted(
        k
        for k, v in fields.items()
        if v is None and k in {"title", "description", "priority", "tags"}
    )
    if nulls:
        raise InvalidInput(
            "Fields cannot be null",
            details={"fields": [{"loc": ["body", k], "message": "cannot be null"} for k in nulls]},
        )

    changes_made: list[str] = []
    last_event: IncidentEvent | None = None
    for name, value in fields.items():
        old = getattr(incident, name)
        if old == value:
            continue
        setattr(incident, name, value)
        changes_made.append(describe_change(name, old, value))
        if name == "priority":
            response_due, resolution_due = compute_due(incident.created_at, value, settings)
            last_event = record_event(
                session,
                incident,
                actor,
                EventType.PRIORITY_CHANGED,
                field="priority",
                old={
                    "priority": old.value,
                    "resolution_due_at": incident.resolution_due_at.isoformat(),
                },
                new={"priority": value.value, "resolution_due_at": resolution_due.isoformat()},
            )
            incident.resolution_due_at = resolution_due
            if incident.first_response_at is None:
                incident.response_due_at = response_due
        else:
            last_event = record_event(
                session, incident, actor, EventType.UPDATED, field=name, old=old, new=value
            )

    incident.updated_at = utcnow()
    if last_event is not None:  # one email for the whole edit, listing every change
        await notification_service.notify(
            session,
            settings,
            NotificationKind.INCIDENT_UPDATED,
            incident,
            last_event,
            actor=actor,
            body="\n".join(changes_made),
        )
    await session.commit()
    return await load(session, incident.id, actor)


# ---------------------------------------------------------------- assign


async def assign(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    raw_ident: str,
    assignee_id: uuid.UUID | None,
) -> Incident:
    """One person (or nobody): the list page's quick assign and AI suggestions."""
    return await set_assignees(
        session, settings, actor, raw_ident, [assignee_id] if assignee_id else []
    )


MAX_ASSIGNEES = 10


def _unique(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


def _write_assignees(session: AsyncSession, incident_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    for position, uid in enumerate(ids):
        session.add(IncidentAssignee(incident_id=incident_id, user_id=uid, position=position))


async def set_assignees(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    raw_ident: str,
    user_ids: list[uuid.UUID],
) -> Incident:
    """Replace who is assigned (in order: the first is the lead). Newly assigned people
    are emailed; everyone added or removed is recorded in the timeline."""
    incident = await load_live(session, parse_ident(raw_ident), actor)
    if not perms.can_assign(actor, incident):
        raise PermissionDenied("You cannot assign this task")
    wanted = _unique(user_ids)
    if len(wanted) > MAX_ASSIGNEES:
        raise InvalidInput(f"A task can have at most {MAX_ASSIGNEES} assignees", code="too_many")
    current = [u.id for u in incident.assignees]
    if wanted == current:
        return incident  # no-op, no event
    if not wanted and incident.status == Status.IN_PROGRESS:
        raise InvalidTransition("Pause the task before unassigning it", code="assignee_required")

    people = {
        uid: await _validate_assignee(session, actor, uid) for uid in wanted if uid not in current
    }
    known = {u.id: u for u in incident.assignees}
    now = utcnow()

    await session.execute(
        sql_delete(IncidentAssignee).where(IncidentAssignee.incident_id == incident.id)
    )
    await session.flush()
    _write_assignees(session, incident.id, wanted)
    incident.assignee_id = wanted[0] if wanted else None
    if wanted:
        _mark_first_response(incident, now)

    removed = [known[uid] for uid in current if uid not in wanted]
    added = [people[uid] for uid in wanted if uid in people]
    last = None
    if len(removed) == 1 and len(added) == 1:
        # A straight swap reads as one "reassigned from A to B" line in the timeline.
        last = record_event(
            session,
            incident,
            actor,
            EventType.ASSIGNED,
            field="assignee",
            old=_user_ref(removed[0]),
            new=_user_ref(added[0]),
        )
    else:
        for person in removed:
            record_event(
                session,
                incident,
                actor,
                EventType.UNASSIGNED,
                field="assignee",
                old=_user_ref(person),
            )
        for person in added:
            last = record_event(
                session,
                incident,
                actor,
                EventType.ASSIGNED,
                field="assignee",
                new=_user_ref(person),
            )
    if last is not None:
        await session.flush()
        await notification_service.notify(
            session,
            settings,
            NotificationKind.INCIDENT_ASSIGNED,
            incident,
            last,
            actor=actor,
            assigned=added,
        )

    incident.updated_at = now
    await session.commit()
    return await load(session, incident.id, actor)


# ---------------------------------------------------------------- lifecycle

STATUS_WORDS = {
    Status.OPEN: "Open",
    Status.IN_PROGRESS: "In progress",
    Status.RESOLVED: "Resolved",
    Status.CLOSED: "Closed",
}


async def transition(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    raw_ident: str,
    new: Status,
    note: str | None = None,
) -> Incident:
    incident = await load_live(session, parse_ident(raw_ident), actor)
    old = incident.status
    if new not in perms.ALLOWED[old]:
        raise InvalidTransition(
            f"Cannot move from {old.value} to {new.value}",
            details={
                "from": old.value,
                "to": new.value,
                "allowed": sorted(s.value for s in perms.ALLOWED[old]),
            },
        )
    if not perms.can_transition(actor, incident, new):
        raise PermissionDenied(f"You cannot move this task to {new.value}")
    if new == Status.IN_PROGRESS and incident.assignee_id is None:
        raise InvalidInput("Assign someone before starting work", code="assignee_required")

    now = utcnow()
    incident.status = new
    if new == Status.RESOLVED:
        incident.resolved_at = now
    elif new == Status.CLOSED:
        incident.closed_at = now
    elif new == Status.OPEN:
        incident.resolved_at = None
        incident.closed_at = None
    incident.updated_at = now

    changed = record_event(
        session,
        incident,
        actor,
        EventType.STATUS_CHANGED,
        field="status",
        old=old,
        new=new,
        note=note,
    )
    # Resolving is its own email ("resolved"); every other move is an update.
    kind = (
        NotificationKind.INCIDENT_RESOLVED
        if new == Status.RESOLVED
        else NotificationKind.INCIDENT_UPDATED
    )
    status_line = f"Status: {STATUS_WORDS[old]} -> {STATUS_WORDS[new]}"
    await notification_service.notify(
        session,
        settings,
        kind,
        incident,
        changed,
        actor=actor,
        body=f"{status_line}\n{note}" if note else status_line,
    )
    await session.commit()
    log.info("incident_transitioned", incident=incident.key, frm=old.value, to=new.value)
    return await load(session, incident.id, actor)


# ---------------------------------------------------------------- delete / restore


async def delete(session: AsyncSession, actor: User, raw_ident: str) -> None:
    incident = await load_live(session, parse_ident(raw_ident), actor)
    if not perms.can_delete(actor, incident):
        raise PermissionDenied("Only the task's creator or a team admin can delete it")
    incident.is_deleted = True
    incident.deleted_at = utcnow()
    record_event(session, incident, actor, EventType.DELETED)
    await session.commit()


async def restore(session: AsyncSession, actor: User, raw_ident: str) -> Incident:
    if not perms.can_restore(actor):
        raise PermissionDenied("Only team admins can restore tasks")
    incident = await load(session, parse_ident(raw_ident), actor, for_update=True)
    if not incident.is_deleted:
        return incident
    incident.is_deleted = False
    incident.deleted_at = None
    record_event(session, incident, actor, EventType.RESTORED)
    await session.commit()
    return await load(session, incident.id, actor)

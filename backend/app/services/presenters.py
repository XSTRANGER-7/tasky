"""Turn ORM rows into response models, adding the per-viewer extras the UI relies on:
SLA state (computed now, never stored, so never stale), the transitions this viewer may
make, and permission hints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.models import Comment, Incident, IncidentEvent, Status, User
from app.schemas.incident import (
    CommentOut,
    EventOut,
    IncidentOut,
    IncidentPermissions,
    SlaState,
)
from app.schemas.user import UserPublic
from app.services import permissions as perms
from app.services.incident_service import AT_RISK_WINDOW

_PAUSED = frozenset({Status.RESOLVED, Status.CLOSED})


def sla_state(incident: Incident, now: datetime) -> SlaState:
    paused = incident.status in _PAUSED
    if incident.first_response_at is not None:
        response_breached = incident.first_response_at > incident.response_due_at
    else:
        response_breached = not paused and now > incident.response_due_at
    if paused:
        finished = incident.resolved_at or incident.closed_at or now
        resolution_breached = finished > incident.resolution_due_at
        at_risk = False
    else:
        resolution_breached = now > incident.resolution_due_at
        at_risk = not resolution_breached and incident.resolution_due_at - now <= AT_RISK_WINDOW
    return SlaState(
        response_breached=response_breached,
        resolution_breached=resolution_breached,
        at_risk=at_risk,
        paused=paused,
    )


def incident_out(
    incident: Incident,
    actor: User,
    now: datetime,
    *,
    comment_count: int = 0,
    watchers: Sequence[User] = (),
    assigned_by: User | None = None,
) -> IncidentOut:
    return IncidentOut(
        id=incident.id,
        key=incident.key,
        number=incident.number,
        team_id=incident.team_id,
        title=incident.title,
        description=incident.description,
        status=incident.status,
        priority=incident.priority,
        category=incident.category,
        tags=list(incident.tags or []),
        reporter=UserPublic.model_validate(incident.reporter),
        assignee=UserPublic.model_validate(incident.assignee) if incident.assignee else None,
        assignees=[UserPublic.model_validate(u) for u in incident.assigned_users],
        response_due_at=incident.response_due_at,
        resolution_due_at=incident.resolution_due_at,
        first_response_at=incident.first_response_at,
        resolved_at=incident.resolved_at,
        closed_at=incident.closed_at,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        is_deleted=incident.is_deleted,
        comment_count=comment_count,
        watching=any(w.id == actor.id for w in watchers),
        watchers=[UserPublic.model_validate(w) for w in watchers],
        assigned_by=UserPublic.model_validate(assigned_by) if assigned_by else None,
        sla=sla_state(incident, now),
        allowed_transitions=[]
        if incident.is_deleted
        else perms.allowed_transitions(actor, incident),
        permissions=IncidentPermissions(
            can_edit=not incident.is_deleted and perms.can_edit(actor, incident),
            can_assign=not incident.is_deleted and perms.can_assign(actor, incident),
            can_comment=not incident.is_deleted and perms.can_comment(actor),
            can_delete=perms.can_delete(actor, incident),
        ),
    )


def comment_out(comment: Comment, actor: User, now: datetime) -> CommentOut:
    return CommentOut(
        id=comment.id,
        incident_id=comment.incident_id,
        author=UserPublic.model_validate(comment.author),
        body=comment.body,
        is_internal=comment.is_internal,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        can_modify=perms.can_modify_comment(actor, comment, now),
    )


def event_out(event: IncidentEvent) -> EventOut:
    return EventOut(
        id=event.id,
        event_type=event.event_type,
        actor=UserPublic.model_validate(event.actor) if event.actor else None,
        field=event.field,
        old_value=event.old_value,
        new_value=event.new_value,
        note=event.note,
        created_at=event.created_at,
    )

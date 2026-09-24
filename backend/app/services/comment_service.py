"""Comments: members and admins comment; authors may edit/delete their own for 15 minutes,
admins any time. Internal notes are hidden from viewers. Every change is audited."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFound, PermissionDenied
from app.db.base import utcnow
from app.models import Comment, EventType, NotificationKind, User
from app.repositories import incident_repo
from app.services import incident_service, notification_service
from app.services import permissions as perms
from app.services.team_scope import team_id_of

PREVIEW_CHARS = 140


def _preview(body: str) -> str:
    flat = " ".join(body.split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 1] + "…"


async def list_for(session: AsyncSession, actor: User, raw_ident: str) -> Sequence[Comment]:
    incident = await incident_service.get(session, actor, raw_ident)
    return await incident_repo.list_comments(
        session, incident.id, include_internal=perms.can_see_internal(actor)
    )


async def add(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    raw_ident: str,
    *,
    body: str,
    is_internal: bool,
) -> Comment:
    if not perms.can_comment(actor):
        raise PermissionDenied("Viewers cannot comment")
    incident = await incident_service.load_live(
        session, incident_service.parse_ident(raw_ident), actor
    )

    now = utcnow()
    comment = Comment(
        incident_id=incident.id,
        author_id=actor.id,
        body=body,
        is_internal=is_internal,
        created_at=now,
    )
    session.add(comment)
    await session.flush()
    if actor.id != incident.reporter_id and incident.first_response_at is None:
        incident.first_response_at = now
    incident.updated_at = now
    event = incident_service.record_event(
        session,
        incident,
        actor,
        EventType.COMMENTED,
        new={"comment_id": str(comment.id), "preview": _preview(body), "internal": is_internal},
    )
    await notification_service.notify(
        session,
        settings,
        NotificationKind.INCIDENT_COMMENTED,
        incident,
        event,
        actor=actor,
        body=body,
        internal=is_internal,
    )
    await session.commit()
    return await _reload(session, comment.id)


async def _editable(session: AsyncSession, actor: User, comment_id: uuid.UUID) -> Comment:
    comment = await incident_repo.get_comment(session, comment_id)
    if comment is None or (comment.is_internal and not perms.can_see_internal(actor)):
        raise NotFound("Comment not found")
    incident = await incident_repo.get_incident(session, comment.incident_id)
    if incident is None or incident.is_deleted or incident.team_id != team_id_of(actor):
        raise NotFound("Comment not found")
    if not perms.can_modify_comment(actor, comment, utcnow()):
        raise PermissionDenied(
            "You can only change your own comments, within 15 minutes of posting",
            code="comment_locked",
        )
    return comment


async def edit(session: AsyncSession, actor: User, comment_id: uuid.UUID, *, body: str) -> Comment:
    comment = await _editable(session, actor, comment_id)
    if comment.body == body:
        return comment
    incident = await incident_repo.get_incident(session, comment.incident_id)
    assert incident is not None  # noqa: S101 - checked in _editable
    old = comment.body
    comment.body = body
    comment.edited_at = utcnow()
    incident_service.record_event(
        session,
        incident,
        actor,
        EventType.COMMENT_EDITED,
        field="comment",
        old={"comment_id": str(comment.id), "preview": _preview(old)},
        new={"comment_id": str(comment.id), "preview": _preview(body)},
    )
    await session.commit()
    return await _reload(session, comment.id)


async def delete(session: AsyncSession, actor: User, comment_id: uuid.UUID) -> None:
    comment = await _editable(session, actor, comment_id)
    incident = await incident_repo.get_incident(session, comment.incident_id)
    assert incident is not None  # noqa: S101 - checked in _editable
    comment.is_deleted = True
    incident_service.record_event(
        session,
        incident,
        actor,
        EventType.COMMENT_DELETED,
        field="comment",
        old={"comment_id": str(comment.id), "preview": _preview(comment.body)},
    )
    await session.commit()


async def _reload(session: AsyncSession, comment_id: uuid.UUID) -> Comment:
    comment = await incident_repo.get_comment(session, comment_id)
    assert comment is not None  # noqa: S101 - just written in this session
    return comment

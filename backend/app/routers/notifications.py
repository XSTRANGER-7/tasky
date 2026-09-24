"""/api/v1/notifications (own in-app items + email log) and /api/v1/admin/outbox."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import joinedload

from app.core.deps import AppSettings, CurrentUser, DbSession, TeamAdmin
from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import InAppNotification, Incident, NotificationOutbox, OutboxStatus
from app.models.incident import key_for
from app.notifications import delivery
from app.schemas.notification import (
    EmailLogItem,
    InAppNotificationOut,
    NotificationList,
    OutboxPage,
    OutboxRow,
)
from app.schemas.user import UserPublic
from app.services.team_scope import team_id_of
from app.services.worker_status import worker_status

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
# A team's admins watch and retry their own team's email (not other teams', not account mail).
admin = APIRouter(prefix="/api/v1/admin", tags=["admin"])

Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("", response_model=NotificationList, summary="My in-app notifications")
async def list_notifications(
    session: DbSession,
    actor: CurrentUser,
    unread: Annotated[bool, Query(description="Only unread items")] = False,
    limit: Limit = 50,
) -> NotificationList:
    # Team and account notifications have no incident; incident ones hide once deleted.
    visible = or_(InAppNotification.incident_id.is_(None), Incident.is_deleted.is_(False))
    stmt = (
        select(InAppNotification, Incident.number)
        .outerjoin(Incident, Incident.id == InAppNotification.incident_id)
        .where(InAppNotification.user_id == actor.id, visible)
        .options(joinedload(InAppNotification.actor))
        .order_by(InAppNotification.created_at.desc(), InAppNotification.id.desc())
        .limit(limit)
    )
    if unread:
        stmt = stmt.where(InAppNotification.read_at.is_(None))
    rows = (await session.execute(stmt)).all()
    unread_count = int(
        await session.scalar(
            select(func.count())
            .select_from(InAppNotification)
            .outerjoin(Incident, Incident.id == InAppNotification.incident_id)
            .where(
                InAppNotification.user_id == actor.id,
                InAppNotification.read_at.is_(None),
                visible,
            )
        )
        or 0
    )
    return NotificationList(
        items=[
            InAppNotificationOut(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                incident_id=n.incident_id,
                incident_key=key_for(number) if number is not None else None,
                team_id=n.team_id,
                link=n.link,
                actor=UserPublic.model_validate(n.actor) if n.actor else None,
                read_at=n.read_at,
                created_at=n.created_at,
            )
            for n, number in rows
        ],
        unread_count=unread_count,
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="Mark all as read")
async def read_all(session: DbSession, actor: CurrentUser) -> Response:
    await session.execute(
        update(InAppNotification)
        .where(InAppNotification.user_id == actor.id, InAppNotification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="Mark one read"
)
async def read_one(notification_id: uuid.UUID, session: DbSession, actor: CurrentUser) -> Response:
    result = await session.execute(
        update(InAppNotification)
        .where(InAppNotification.id == notification_id, InAppNotification.user_id == actor.id)
        .values(read_at=func.coalesce(InAppNotification.read_at, utcnow()))
        .returning(InAppNotification.id)
    )
    if result.first() is None:
        raise NotFound("Notification not found")  # also for other people's notifications
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/emails", response_model=list[EmailLogItem], summary="My email log")
async def my_emails(
    session: DbSession, actor: CurrentUser, limit: Limit = 50
) -> list[EmailLogItem]:
    rows = (
        await session.execute(
            select(NotificationOutbox, Incident.number)
            .outerjoin(Incident, Incident.id == NotificationOutbox.incident_id)
            .where(NotificationOutbox.recipient_user_id == actor.id)
            .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        EmailLogItem(
            id=o.id,
            kind=o.kind,
            subject=o.subject,
            incident_key=key_for(number) if number is not None else None,
            status=o.status,
            attempts=o.attempts,
            created_at=o.created_at,
            sent_at=o.sent_at,
        )
        for o, number in rows
    ]


# ---------------------------------------------------------------- admin outbox


@admin.get("/outbox", response_model=OutboxPage, summary="This team's email outbox (team admins)")
async def outbox(
    session: DbSession,
    settings: AppSettings,
    actor: TeamAdmin,
    status_: Annotated[OutboxStatus | None, Query(alias="status")] = None,
    limit: Limit = 100,
) -> OutboxPage:
    team_id = team_id_of(actor)
    stmt = (
        select(NotificationOutbox, Incident.number)
        .outerjoin(Incident, Incident.id == NotificationOutbox.incident_id)
        .where(NotificationOutbox.team_id == team_id)
        .options(joinedload(NotificationOutbox.recipient))
        .order_by(NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc())
        .limit(limit)
    )
    if status_:
        stmt = stmt.where(NotificationOutbox.status == status_)
    rows = (await session.execute(stmt)).all()
    return OutboxPage(
        items=[
            OutboxRow(
                id=o.id,
                kind=o.kind,
                subject=o.subject,
                incident_key=key_for(number) if number is not None else None,
                status=o.status,
                attempts=o.attempts,
                created_at=o.created_at,
                sent_at=o.sent_at,
                recipient_email=o.recipient_email,
                recipient=UserPublic.model_validate(o.recipient),
                last_error=o.last_error,
                next_attempt_at=o.next_attempt_at,
            )
            for o, number in rows
        ],
        counts=await delivery.counts(session, team_id),
        worker=await worker_status(session, settings),
    )


@admin.post(
    "/outbox/{outbox_id}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retry one of this team's failed emails (team admins)",
    description="Resets a failed row to pending with a fresh attempt budget; the worker "
    "picks it up on its next poll.",
)
async def retry(outbox_id: uuid.UUID, session: DbSession, actor: TeamAdmin) -> Response:
    row = await session.get(NotificationOutbox, outbox_id, with_for_update=True)
    if row is None or row.team_id != team_id_of(actor):
        raise NotFound("Outbox row not found")
    if row.status != OutboxStatus.FAILED:
        raise Conflict("Only failed emails can be retried", code="not_failed")
    row.status = OutboxStatus.PENDING
    row.attempts = 0
    row.next_attempt_at = utcnow()
    await session.commit()
    log.info("outbox_retry", outbox_id=str(outbox_id), by=str(actor.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""SLA breach checker: runs every SLA_CHECK_SECONDS inside the worker (spec 6, 9.1).

Finds open work past its resolution deadline that has not been flagged *for that
deadline*, records an ``sla_breached`` audit event and notifies the owner (assignee, else
reporter) by email plus every admin in-app. Exactly once per breach: the event stores the
deadline it flagged (as epoch seconds, compared as integers in SQL), so a priority change
(new deadline) can breach again, while re-runs, restarts and parallel workers cannot
duplicate it (candidate rows are locked with SKIP LOCKED).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, and_, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import EventType, Incident, IncidentEvent, NotificationKind, Status
from app.models.incident import key_for
from app.services import incident_service, notification_service

log = get_logger(__name__)


def epoch(value: datetime) -> int:
    return int(value.timestamp())


async def check(session: AsyncSession, settings: Settings, *, limit: int = 100) -> int:
    now = utcnow()
    due_epoch = cast(func.floor(func.extract("epoch", Incident.resolution_due_at)), BigInteger)
    already_flagged = exists().where(
        and_(
            IncidentEvent.incident_id == Incident.id,
            IncidentEvent.event_type == EventType.SLA_BREACHED,
            IncidentEvent.new_value["due_epoch"].as_integer() == due_epoch,
        )
    )
    breached = (
        (
            await session.scalars(
                select(Incident)
                .where(
                    Incident.is_deleted.is_(False),
                    Incident.status.in_((Status.OPEN, Status.IN_PROGRESS)),
                    Incident.resolution_due_at < now,
                    ~already_flagged,
                )
                .order_by(Incident.resolution_due_at)
                .limit(limit)
                .with_for_update(skip_locked=True, of=Incident)
                .options(joinedload(Incident.reporter), joinedload(Incident.assignee))
            )
        )
        .unique()
        .all()
    )

    for incident in breached:
        overdue = int((now - incident.resolution_due_at).total_seconds() // 60)
        event = incident_service.record_event(
            session,
            incident,
            None,
            EventType.SLA_BREACHED,
            field="sla",
            new={
                "resolution_due_at": incident.resolution_due_at.isoformat(),
                "due_epoch": epoch(incident.resolution_due_at),
                "overdue_minutes": overdue,
            },
        )
        await notification_service.notify(
            session, settings, NotificationKind.SLA_BREACHED, incident, event, actor=None
        )
        log.warning("sla_breached", incident=key_for(incident.number), overdue_minutes=overdue)
    await session.commit()
    return len(breached)

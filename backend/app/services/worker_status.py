"""How long since the notification worker last beat -- for /health and the admin outbox."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.base import utcnow
from app.models import WorkerHeartbeat
from app.notifications.worker import HEARTBEAT_NAME
from app.schemas.notification import WorkerStatus


async def worker_status(session: AsyncSession, settings: Settings) -> WorkerStatus:
    beat = await session.get(WorkerHeartbeat, HEARTBEAT_NAME)
    if beat is None:
        return WorkerStatus(status="unknown", last_beat_at=None, seconds_since_beat=None)
    age = (utcnow() - beat.beat_at).total_seconds()
    return WorkerStatus(
        status="ok" if age <= settings.worker_stale_seconds else "stale",
        last_beat_at=beat.beat_at,
        seconds_since_beat=round(age, 1),
    )

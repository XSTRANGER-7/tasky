from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import NotificationKind, OutboxStatus
from app.schemas.user import UserPublic


class InAppNotificationOut(BaseModel):
    id: uuid.UUID
    kind: NotificationKind
    title: str
    body: str
    incident_id: uuid.UUID | None
    incident_key: str | None
    team_id: uuid.UUID | None = None
    link: str | None = Field(
        default=None, description="Where to open non-incident notifications in the app"
    )
    actor: UserPublic | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[InAppNotificationOut]
    unread_count: int


class EmailLogItem(BaseModel):
    """The caller's own email log (spec 9.8): what was sent to them, and whether it went."""

    id: uuid.UUID
    kind: NotificationKind
    subject: str
    incident_key: str | None
    status: OutboxStatus
    attempts: int
    created_at: datetime
    sent_at: datetime | None


class OutboxRow(EmailLogItem):
    """Admin view: everything above plus the recipient and the last error."""

    recipient_email: str
    recipient: UserPublic
    last_error: str | None
    next_attempt_at: datetime


class OutboxPage(BaseModel):
    items: list[OutboxRow]
    counts: dict[str, int]
    worker: WorkerStatus


class WorkerStatus(BaseModel):
    status: str  # ok | stale | unknown
    last_beat_at: datetime | None
    seconds_since_beat: float | None


OutboxPage.model_rebuild()

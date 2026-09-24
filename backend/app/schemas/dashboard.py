from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models import EventType
from app.schemas.user import UserPublic


class AssigneeCount(BaseModel):
    user: UserPublic | None  # None = unassigned
    count: int


class SlaSummary(BaseModel):
    breached: int
    at_risk_next_hour: int


class Mttr(BaseModel):
    last_7d: float | None  # hours; None when nothing was resolved in the window
    last_30d: float | None


class TrendPoint(BaseModel):
    date: date
    created: int
    resolved: int


class ActivityItem(BaseModel):
    id: uuid.UUID
    event_type: EventType
    actor: UserPublic | None
    incident_id: uuid.UUID
    incident_key: str
    incident_title: str
    field: str | None
    old_value: object | None
    new_value: object | None
    created_at: datetime


class DashboardSummary(BaseModel):
    counts: dict[str, int]
    by_priority: dict[str, int]  # open work only
    open_by_assignee: list[AssigneeCount]
    sla: SlaSummary
    mttr_hours: Mttr
    trend_14d: list[TrendPoint]
    recent_activity: list[ActivityItem]
    generated_at: datetime

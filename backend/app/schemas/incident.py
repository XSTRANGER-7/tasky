from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import EventType, Priority, Status
from app.schemas.user import UserPublic

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=20000)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Tag = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, min_length=1, max_length=30, pattern=r"^[\w\-.]+$"
    ),
]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
CommentBody = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]


def _dedupe_tags(tags: list[str] | None) -> list[str] | None:
    return None if tags is None else list(dict.fromkeys(tags))


# ---------------------------------------------------------------- requests


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description = ""
    priority: Priority = Priority.MEDIUM
    category: Category | None = None
    tags: Annotated[list[Tag], Field(max_length=10)] = []
    assignee_id: uuid.UUID | None = None  # one person; or assignee_ids for several
    assignee_ids: Annotated[list[uuid.UUID], Field(max_length=10)] | None = None

    @field_validator("tags")
    @classmethod
    def _dedupe(cls, tags: list[str] | None) -> list[str] | None:
        return _dedupe_tags(tags)


class IncidentUpdate(BaseModel):
    """Partial update; every changed field is audited. Status and assignee have their own
    endpoints because they carry their own rules and side effects."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: Description | None = None
    priority: Priority | None = None
    category: Category | None = None
    tags: Annotated[list[Tag], Field(max_length=10)] | None = None

    @field_validator("tags")
    @classmethod
    def _dedupe(cls, tags: list[str] | None) -> list[str] | None:
        return _dedupe_tags(tags)


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: uuid.UUID | None = Field(description="User id, or null to unassign")


class TransitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    note: Note | None = None


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CommentBody
    is_internal: bool = False


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CommentBody


# ---------------------------------------------------------------- responses


class SlaState(BaseModel):
    response_breached: bool
    resolution_breached: bool
    at_risk: bool = Field(description="Open work due within the next hour")
    paused: bool = Field(description="Resolved/closed: the clock no longer runs")


class IncidentPermissions(BaseModel):
    can_edit: bool
    can_assign: bool
    can_comment: bool
    can_delete: bool


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str = Field(examples=["INC-142"])
    number: int
    team_id: uuid.UUID
    title: str
    description: str
    status: Status
    priority: Priority
    category: str | None
    tags: list[str]
    reporter: UserPublic = Field(description="Who created the task")
    assignee: UserPublic | None = Field(description="The lead: the first of `assignees`")
    assignees: list[UserPublic] = []
    response_due_at: datetime
    resolution_due_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    comment_count: int = 0
    watching: bool = False
    watchers: list[UserPublic] = []
    # Who made the latest assignment (single-task responses only; null in lists).
    assigned_by: UserPublic | None = None
    sla: SlaState
    allowed_transitions: list[Status]
    permissions: IncidentPermissions


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    author: UserPublic
    body: str
    is_internal: bool
    created_at: datetime
    edited_at: datetime | None
    can_modify: bool = False


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: EventType
    actor: UserPublic | None
    field: str | None
    old_value: Any | None
    new_value: Any | None
    note: str | None
    created_at: datetime

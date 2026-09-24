from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import inspect as orm_inspect
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.user import User


def _pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


# Human keys: TASK-142. Links from before the rename (INC-142) still resolve.
KEY_PREFIX = "TASK"
KEY_PATTERN = r"(?:TASK-|INC-)?(\d{1,18})"


def key_for(number: int) -> str:
    return f"{KEY_PREFIX}-{number}"


class Status(enum.StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Priority(enum.StrEnum):
    # Declaration order is the Postgres enum sort order: ORDER BY priority DESC puts
    # critical first, and keyset pagination can compare priorities directly.
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    COMMENTED = "commented"
    COMMENT_EDITED = "comment_edited"
    COMMENT_DELETED = "comment_deleted"
    DELETED = "deleted"
    RESTORED = "restored"
    WATCHER_ADDED = "watcher_added"
    WATCHER_REMOVED = "watcher_removed"
    SLA_BREACHED = "sla_breached"
    ATTACHMENT_ADDED = "attachment_added"
    ATTACHMENT_DELETED = "attachment_deleted"
    AI_APPLIED = "ai_applied"


class Incident(UUIDPk, Timestamps, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 3 AND 200", name="title_length"),
        CheckConstraint("char_length(description) <= 20000", name="description_length"),
        # The default list query: filter by status/priority, newest first.
        Index(
            "ix_incidents_status_priority_created",
            "status",
            "priority",
            text("created_at DESC"),
            postgresql_where=text("NOT is_deleted"),
        ),
        Index(
            "ix_incidents_assignee_active",
            "assignee_id",
            postgresql_where=text("NOT is_deleted"),
        ),
        Index("ix_incidents_created_at", text("created_at DESC")),
        # Every list, search and dashboard query is scoped to one team.
        Index(
            "ix_incidents_team_created",
            "team_id",
            text("created_at DESC"),
            postgresql_where=text("NOT is_deleted"),
        ),
        # The SLA breach checker scans only open work.
        Index(
            "ix_incidents_resolution_due_open",
            "resolution_due_at",
            postgresql_where=text("status IN ('open', 'in_progress')"),
        ),
        Index("ix_incidents_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_incidents_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[Status] = mapped_column(
        _pg_enum(Status, "incident_status"), default=Status.OPEN, server_default="open"
    )
    priority: Mapped[Priority] = mapped_column(
        _pg_enum(Priority, "incident_priority"), default=Priority.MEDIUM, server_default="medium"
    )
    category: Mapped[str | None] = mapped_column(String(50))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), default=list, server_default=text("'{}'::varchar[]")
    )

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    response_due_at: Mapped[datetime]
    resolution_due_at: Mapped[datetime]
    first_response_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]

    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false")
    deleted_at: Mapped[datetime | None]

    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        deferred=True,
    )

    reporter: Mapped[User] = relationship(foreign_keys=[reporter_id], lazy="raise")
    # The lead assignee: always the first of ``assignees`` (NULL when nobody is assigned).
    # Kept so sorting, the SLA owner and AI suggestions have one person to talk about.
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="raise")
    # Everyone assigned, lead first. Written only through incident_service.set_assignees.
    assignees: Mapped[list[User]] = relationship(
        secondary="incident_assignees",
        order_by="IncidentAssignee.position",
        lazy="raise",
        viewonly=True,
    )

    @property
    def key(self) -> str:
        return key_for(self.number)

    @property
    def assigned_users(self) -> list[User]:
        """``assignees`` when loaded, else just the lead (never triggers a query)."""
        if "assignees" not in orm_inspect(self).unloaded:
            return list(self.assignees)
        if "assignee" not in orm_inspect(self).unloaded and self.assignee is not None:
            return [self.assignee]
        return []

    @property
    def assignee_ids(self) -> frozenset[uuid.UUID]:
        ids = {u.id for u in self.assigned_users}
        if self.assignee_id is not None:
            ids.add(self.assignee_id)
        return frozenset(ids)


class IncidentAssignee(Base):
    """One person assigned to an incident; ``position`` 0 is the lead."""

    __tablename__ = "incident_assignees"
    __table_args__ = (Index("ix_incident_assignees_user", "user_id"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)


class Comment(UUIDPk, Base):
    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 5000", name="body_length"),
        Index("ix_comments_incident_created", "incident_id", "created_at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
    is_internal: Mapped[bool] = mapped_column(default=False, server_default="false")
    edited_at: Mapped[datetime | None]
    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    author: Mapped[User] = relationship(lazy="raise")


class IncidentEvent(UUIDPk, Base):
    """Append-only audit log. Rows are only ever inserted."""

    __tablename__ = "incident_events"
    __table_args__ = (
        Index("ix_incident_events_incident_created", "incident_id", "created_at"),
        Index("ix_incident_events_seq", text("seq DESC")),
    )

    # Insertion order. Events written in one transaction can share a timestamp, so the
    # timeline orders by this, never by (created_at, random uuid).
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)

    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event_type: Mapped[EventType] = mapped_column(_pg_enum(EventType, "incident_event_type"))
    field: Mapped[str | None] = mapped_column(String(50))
    old_value: Mapped[Any | None] = mapped_column(JSONB)
    new_value: Mapped[Any | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    actor: Mapped[User | None] = relationship(lazy="raise")


class IdempotencyKey(Base):
    """``Idempotency-Key`` on POST /incidents: a retried create returns the original."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_keys_user_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

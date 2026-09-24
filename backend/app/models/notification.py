from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPk, utcnow
from app.models.user import User


class NotificationKind(enum.StrEnum):
    INCIDENT_ASSIGNED = "incident_assigned"
    INCIDENT_RESOLVED = "incident_resolved"
    INCIDENT_UPDATED = "incident_updated"  # status change or edit (not resolve)
    INCIDENT_ADDED = "incident_added"  # someone added you to follow an incident
    INCIDENT_COMMENTED = "incident_commented"
    MENTIONED = "mentioned"
    SLA_BREACHED = "sla_breached"
    TEAM_JOIN_REQUESTED = "team_join_requested"
    TEAM_JOIN_APPROVED = "team_join_approved"
    TEAM_JOIN_REJECTED = "team_join_rejected"
    TEAM_MEMBER_ADDED = "team_member_added"
    TEAM_ROLE_CHANGED = "team_role_changed"
    TEAM_MEMBER_REMOVED = "team_member_removed"
    PASSWORD_RESET = "password_reset"  # noqa: S105 - a kind label; email only, never in-app


# Kinds about one incident (rendered by ``render_email``); the rest are team or account mail.
INCIDENT_KINDS = frozenset(
    {
        NotificationKind.INCIDENT_ASSIGNED,
        NotificationKind.INCIDENT_RESOLVED,
        NotificationKind.INCIDENT_UPDATED,
        NotificationKind.INCIDENT_ADDED,
        NotificationKind.INCIDENT_COMMENTED,
        NotificationKind.MENTIONED,
        NotificationKind.SLA_BREACHED,
    }
)


class OutboxStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


def _pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class NotificationOutbox(UUIDPk, Base):
    """Transactional email queue. Written in the same transaction as the change that
    caused it; delivered later by the worker. The rendered email is snapshotted here,
    so the row records exactly what was (or will be) sent."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "recipient_user_id", "kind", name="uq_notification_outbox_event_user_kind"
        ),
        # The worker's poll: only pending rows, oldest due first.
        Index(
            "ix_notification_outbox_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_notification_outbox_recipient_created", "recipient_user_id", "created_at"),
        Index("ix_notification_outbox_team_created", "team_id", "created_at"),
    )

    # Null for mail that is not about an incident (team requests, password resets).
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incident_events.id", ondelete="CASCADE")
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE")
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The team the mail is about (null for account mail such as password resets), so each
    # team's admins see and retry only their own team's email.
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    recipient_email: Mapped[str] = mapped_column(String(320))
    kind: Mapped[NotificationKind] = mapped_column(_pg_enum(NotificationKind, "notification_kind"))
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text)
    status: Mapped[OutboxStatus] = mapped_column(
        _pg_enum(OutboxStatus, "outbox_status"),
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    recipient: Mapped[User] = relationship(lazy="raise")


class InAppNotification(UUIDPk, Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "user_id", "kind", name="uq_in_app_notifications_event_user_kind"
        ),
        Index("ix_in_app_notifications_user_read", "user_id", "read_at"),
        Index("ix_in_app_notifications_user_created", "user_id", text("created_at DESC")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE")
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incident_events.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    # Where the notification opens in the SPA, for non-incident kinds (e.g. /team/requests).
    link: Mapped[str | None] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[NotificationKind] = mapped_column(_pg_enum(NotificationKind, "notification_kind"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(String(400))
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id], lazy="raise")


class IncidentWatcher(Base):
    __tablename__ = "incident_watchers"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    user: Mapped[User] = relationship(lazy="raise")


class WorkerHeartbeat(Base):
    """One row per worker loop; /health reports how long ago it last beat."""

    __tablename__ = "worker_heartbeats"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    beat_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

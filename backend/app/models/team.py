"""Teams: every incident belongs to one team, and people see only their teams' work.

There is no platform-wide admin. Whoever creates a team is its admin; admin rights stop
at the edge of that team.

* ``TeamMembership.role`` decides what a person may do inside that team, through the
  incident permission matrix (``permissions.py``, via :meth:`TeamRole.as_role`).
* Joining is by request: the team's admins approve (as member, viewer or admin) or
  reject it. A team always keeps at least one admin.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow
from app.models.user import Role, User


def _pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class TeamRole(enum.StrEnum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    def as_role(self) -> Role:
        """The incident-permission role this team role grants."""
        return Role(self.value)

    @property
    def manages_team(self) -> bool:
        """May approve join requests, manage members and delete the team."""
        return self == TeamRole.ADMIN


class JoinRequestStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Team(UUIDPk, Timestamps, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(CITEXT, unique=True)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    memberships: Mapped[list[TeamMembership]] = relationship(
        back_populates="team", cascade="all, delete-orphan", passive_deletes=True
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (Index("ix_team_memberships_user_id", "user_id"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[TeamRole] = mapped_column(
        _pg_enum(TeamRole, "team_role"),
        default=TeamRole.MEMBER,
        server_default=TeamRole.MEMBER.value,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    team: Mapped[Team] = relationship(back_populates="memberships", lazy="raise")
    user: Mapped[User] = relationship(lazy="raise")


class TeamJoinRequest(UUIDPk, Base):
    __tablename__ = "team_join_requests"
    __table_args__ = (
        # At most one open request per person and team.
        Index(
            "uq_team_join_requests_pending",
            "team_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_team_join_requests_team_status", "team_id", "status"),
        Index("ix_team_join_requests_user_id", "user_id"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[JoinRequestStatus] = mapped_column(
        _pg_enum(JoinRequestStatus, "join_request_status"),
        default=JoinRequestStatus.PENDING,
        server_default=JoinRequestStatus.PENDING.value,
    )
    granted_role: Mapped[TeamRole | None] = mapped_column(_pg_enum(TeamRole, "team_role"))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    team: Mapped[Team] = relationship(lazy="raise")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="raise")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="raise")

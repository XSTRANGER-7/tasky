from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, utcnow

if TYPE_CHECKING:
    from app.models.team import TeamRole


class Role(enum.StrEnum):
    """Permission level inside a team (see ``permissions.py``). Accounts have no global
    role: what someone may do comes from their ``TeamMembership`` in each team."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    # The team context below is request-scoped state, not columns.
    __allow_unmapped__ = True

    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(CITEXT, unique=True)  # case-insensitive uniqueness
    # None for accounts that only sign in with Google.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    # Id of this account's copy in Supabase Auth, once copied (see services/supabase_auth).
    supabase_auth_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    # Set once the first-sign-in "create a team?" page has been answered.
    onboarded_at: Mapped[datetime | None]
    # Profile photo in file storage ("avatars/<random>.<ext>"); a new key per upload, so
    # the served image can be cached forever.
    avatar_key: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    avatar_color: Mapped[str] = mapped_column(String(7))
    notify_email: Mapped[bool] = mapped_column(default=True, server_default="true")

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    # Set per request by ``deps.get_team_user`` for team-scoped routes (never persisted).
    active_team_id: uuid.UUID | None = None
    active_team_role: TeamRole | None = None

    @property
    def avatar_url(self) -> str | None:
        if not self.avatar_key:
            return None
        return f"/api/v1/avatars/{self.avatar_key.removeprefix('avatars/')}"

    @property
    def onboarded(self) -> bool:
        return self.onboarded_at is not None

    @property
    def effective_role(self) -> Role:
        """The role that governs incident permissions: the one this person holds in the
        active team. Without a team context it is the least privileged (fail closed)."""
        if self.active_team_role is not None:
            return self.active_team_role.as_role()
        return Role.VIEWER

    @property
    def role(self) -> Role:
        """Read-only alias of :attr:`effective_role` (the role in the active team), so a
        ``User`` satisfies ``permissions.Actor``. Accounts have no global role."""
        return self.effective_role

    def __repr__(self) -> str:  # never include the hash
        return f"<User {self.email}>"


class RefreshToken(UUIDPk, Base):
    """One row per issued refresh token. Only the SHA-256 of the token is stored."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id_active", "user_id", "revoked_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class PasswordResetToken(UUIDPk, Base):
    """Single-use, short-lived. Only the SHA-256 of the emailed token is stored."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_tokens_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

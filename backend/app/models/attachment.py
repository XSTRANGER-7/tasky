from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPk, utcnow
from app.models.user import User

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class Attachment(UUIDPk, Base):
    """A file on an incident (optionally on one of its comments). The bytes live in object
    storage under a random ``storage_key``; the filename is display-only and never used
    to build a path."""

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            f"size_bytes > 0 AND size_bytes <= {MAX_ATTACHMENT_BYTES}", name="size_limit"
        ),
        Index("ix_attachments_incident_created", "incident_id", "created_at"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL")
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)

    uploader: Mapped[User] = relationship(lazy="joined")

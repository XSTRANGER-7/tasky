from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPk, utcnow


class SuggestionKind(enum.StrEnum):
    TRIAGE = "triage"
    SUMMARY = "summary"
    POSTMORTEM = "postmortem"
    NL_SEARCH = "nl_search"


class SuggestionStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def _pg_enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class AiSuggestion(UUIDPk, Base):
    """Every AI output, kept whether or not anyone acts on it (spec 10): what was
    suggested, by which model and prompt version, how long it took, what it cost, and
    what the human decided. Accepted changes are applied through the service layer."""

    __tablename__ = "ai_suggestions"
    __table_args__ = (
        Index("ix_ai_suggestions_incident_created", "incident_id", "created_at"),
        Index("ix_ai_suggestions_user_created", "user_id", "created_at"),
        Index("ix_ai_suggestions_team_id", "team_id"),
    )

    # NULL for triage before the incident exists, and for NL search.
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The team it was asked in: team admins see usage stats for their own team only.
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    kind: Mapped[SuggestionKind] = mapped_column(_pg_enum(SuggestionKind, "ai_suggestion_kind"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[SuggestionStatus] = mapped_column(
        _pg_enum(SuggestionStatus, "ai_suggestion_status"), default=SuggestionStatus.PENDING
    )
    source: Mapped[str] = mapped_column(String(20))  # "llm" or "rules" (fallback)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(40))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column()

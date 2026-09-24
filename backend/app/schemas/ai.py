"""AI schemas: what the model must return (validated, extra keys rejected) and what the
API returns (with IDs resolved against the database)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Priority, Status, SuggestionKind, SuggestionStatus
from app.schemas.user import UserPublic

Source = Literal["llm", "rules"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- model output


class SimilarRef(_Strict):
    id: uuid.UUID
    score: float = Field(ge=0, le=1)


class TriageOutput(_Strict):
    priority: Priority
    category: str | None = Field(default=None, max_length=50)
    suggested_assignee_id: uuid.UUID | None = None
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(max_length=600)
    similar: list[SimilarRef] = Field(default_factory=list, max_length=5)


class SummaryOutput(_Strict):
    summary: str = Field(max_length=1500)
    current_status: str = Field(max_length=300)
    open_questions: list[str] = Field(default_factory=list, max_length=5)


class PostmortemOutput(_Strict):
    timeline: list[str] = Field(max_length=20)
    probable_root_cause: str = Field(max_length=1500)
    impact: str = Field(max_length=600)
    action_items: list[str] = Field(max_length=8)


SlaFilter = Literal["breached", "at_risk", "on_track"]
SortOption = Literal[
    "-created_at", "created_at", "-updated_at", "-priority,-created_at", "resolution_due_at"
]


class SearchOutput(_Strict):
    status: list[Status] = Field(default_factory=list)
    priority: list[Priority] = Field(default_factory=list)
    assignee: str | None = None  # "me" | "none" | user id (checked after parsing)
    sla: SlaFilter | None = None
    q: str | None = Field(default=None, max_length=200)
    sort: SortOption | None = None


# ---------------------------------------------------------------- API


class AiStatus(BaseModel):
    enabled: bool
    provider: str
    model: str | None
    features: list[str]


class TriageRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=20000)


class SimilarIncident(BaseModel):
    id: uuid.UUID
    key: str
    title: str
    status: Status
    priority: Priority
    score: float


class SuggestedAssignee(BaseModel):
    user: UserPublic
    open_count: int


class TriageSuggestion(BaseModel):
    suggestion_id: uuid.UUID
    source: Source
    model: str
    priority: Priority
    category: str | None
    assignee: SuggestedAssignee | None
    confidence: float
    reasoning: str
    similar: list[SimilarIncident]
    possible_duplicate_of: SimilarIncident | None
    fallback_reason: str | None = None


class SummaryRequest(BaseModel):
    kind: Literal["summary", "postmortem"] = "summary"


class SummarySuggestion(BaseModel):
    suggestion_id: uuid.UUID
    kind: Literal["summary", "postmortem"]
    source: Source
    model: str
    summary: SummaryOutput | None = None
    postmortem: PostmortemOutput | None = None
    markdown: str | None = None  # postmortem rendered as editable Markdown
    fallback_reason: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class SearchSuggestion(BaseModel):
    suggestion_id: uuid.UUID
    source: Source
    model: str
    filters: SearchOutput
    explanation: str
    fallback_reason: str | None = None


ApplyField = Literal["priority", "category", "assignee"]


def _all_fields() -> list[ApplyField]:
    return ["priority", "category", "assignee"]


class AcceptRequest(BaseModel):
    """Triage on an existing incident: which fields to apply. Postmortem: the (edited)
    Markdown to post as an internal note."""

    incident: str | None = Field(default=None, description="INC-12 or UUID (triage)")
    apply: list[ApplyField] = Field(default_factory=_all_fields)
    markdown: str | None = Field(default=None, max_length=20000)


class SuggestionOut(BaseModel):
    id: uuid.UUID
    kind: SuggestionKind
    status: SuggestionStatus
    decided_at: datetime | None

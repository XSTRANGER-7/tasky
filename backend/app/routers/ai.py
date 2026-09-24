"""/api/v1/ai/*: triage, summaries, postmortems, natural-language search (spec 10).

All of it returns suggestions; nothing here changes an incident except ``accept``,
which applies the stored suggestion through the normal (audited) services.
"""

from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, Request

from app.ai.providers import LLMProvider
from app.core.deps import AppSettings, CurrentUser, DbSession, TeamAdmin, TeamUser
from app.core.errors import RateLimited
from app.core.rate_limit import RateLimiter
from app.models import User
from app.schemas.ai import (
    AcceptRequest,
    AiStatus,
    SearchRequest,
    SearchSuggestion,
    SuggestionOut,
    SummaryRequest,
    SummarySuggestion,
    TriageRequest,
    TriageSuggestion,
)
from app.services import ai_service
from app.services.ai_service import DailyBudget
from app.services.team_scope import team_id_of

router = APIRouter(prefix="/api/v1", tags=["ai"])


def _provider(request: Request) -> LLMProvider | None:
    provider: LLMProvider | None = request.app.state.llm
    return provider


def _budget(request: Request) -> DailyBudget:
    budget: DailyBudget = request.app.state.ai_budget
    return budget


async def ai_guard(request: Request, settings: AppSettings, actor: TeamUser) -> User:
    """Enabled check + per-user rate limit (10/min by default)."""
    ai_service.require_enabled(settings)
    if settings.rate_limit_enabled:
        limiter: RateLimiter = request.app.state.rate_limiter
        allowed, _, reset = limiter.hit(f"ai:{actor.id}", settings.ai_rate_limit_per_min, 60.0)
        if not allowed:
            raise RateLimited(
                "Too many AI requests, try again shortly",
                details={"retry_after_seconds": math.ceil(reset)},
                headers={"Retry-After": str(math.ceil(reset))},
            )
    return actor


AiUser = Depends(ai_guard)


@router.get("/ai/status", response_model=AiStatus, summary="Is AI on, and which engine")
async def ai_status(request: Request, settings: AppSettings, _: CurrentUser) -> AiStatus:
    return ai_service.status(settings, _provider(request))


@router.post("/ai/triage", response_model=TriageSuggestion, summary="Suggest triage for a draft")
async def triage(
    body: TriageRequest,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    actor: User = AiUser,
) -> TriageSuggestion:
    return await ai_service.triage(
        session, settings, _provider(request), _budget(request), actor, body.title, body.description
    )


@router.post(
    "/incidents/{ident}/ai/summary",
    response_model=SummarySuggestion,
    summary="Summarise the thread, or draft a postmortem",
)
async def summary(
    ident: str,
    body: SummaryRequest,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    actor: User = AiUser,
) -> SummarySuggestion:
    return await ai_service.summarize(
        session, settings, _provider(request), _budget(request), actor, ident, body.kind
    )


@router.post(
    "/ai/search",
    response_model=SearchSuggestion,
    summary="Natural language to list filters (never runs SQL)",
)
async def search(
    body: SearchRequest,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    actor: User = AiUser,
) -> SearchSuggestion:
    return await ai_service.nl_search(
        session, settings, _provider(request), _budget(request), actor, body.query
    )


@router.post(
    "/ai/suggestions/{suggestion_id}/accept",
    response_model=SuggestionOut,
    summary="Accept: applies the suggestion through the normal, audited services",
)
async def accept(
    suggestion_id: uuid.UUID,
    session: DbSession,
    settings: AppSettings,
    actor: TeamUser,
    body: AcceptRequest | None = None,
) -> SuggestionOut:
    ai_service.require_enabled(settings)
    s = await ai_service.accept(session, settings, actor, suggestion_id, body or AcceptRequest())
    return SuggestionOut(id=s.id, kind=s.kind, status=s.status, decided_at=s.decided_at)


@router.post(
    "/ai/suggestions/{suggestion_id}/reject", response_model=SuggestionOut, summary="Dismiss"
)
async def reject(
    suggestion_id: uuid.UUID, session: DbSession, settings: AppSettings, actor: TeamUser
) -> SuggestionOut:
    ai_service.require_enabled(settings)
    s = await ai_service.reject(session, actor, suggestion_id)
    return SuggestionOut(id=s.id, kind=s.kind, status=s.status, decided_at=s.decided_at)


@router.get(
    "/admin/ai",
    summary="AI usage in this team: accept rate, engine and latency per feature (team admins)",
)
async def ai_stats(session: DbSession, actor: TeamAdmin) -> dict[str, object]:
    return await ai_service.stats(session, team_id_of(actor))

"""AI features (spec 10): suggest, never act.

Every call: rate limited per user, capped per day, LLM first (when configured) with the
rule-based engine as the fallback, output validated and its IDs checked against the
database, and the result stored in ``ai_suggestions`` with model, prompt version,
latency and tokens. Nothing changes until a human accepts, and an accepted change goes
through the normal service layer, so it is permission-checked and audited.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import prompts, rules
from app.ai.providers import AIUnavailable, Completion, InvalidOutput, LLMProvider, Prompt, truncate
from app.ai.tools import DUPLICATE_THRESHOLD, Similar, find_similar_incidents, get_assignee_workload
from app.core.config import Settings
from app.core.errors import AppError, Conflict, InvalidInput, NotFound
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    AiSuggestion,
    EventType,
    IncidentEvent,
    Status,
    SuggestionKind,
    SuggestionStatus,
    User,
)
from app.models.incident import key_for
from app.repositories import incident_repo
from app.schemas.ai import (
    AcceptRequest,
    AiStatus,
    PostmortemOutput,
    SearchOutput,
    SearchSuggestion,
    SimilarIncident,
    SuggestedAssignee,
    SummaryOutput,
    SummarySuggestion,
    TriageOutput,
    TriageSuggestion,
)
from app.schemas.incident import IncidentUpdate
from app.schemas.user import UserPublic
from app.services import comment_service, incident_service, presenters
from app.services.team_scope import team_id_of

log = get_logger(__name__)


# Events that say nothing about what happened during the incident.
TIMELINE_NOISE = frozenset(
    {
        EventType.WATCHER_ADDED,
        EventType.WATCHER_REMOVED,
        EventType.COMMENT_EDITED,
        EventType.COMMENT_DELETED,
        EventType.AI_APPLIED,
    }
)


class AiDisabled(AppError):
    status_code = 503
    code = "ai_disabled"


# ---------------------------------------------------------------- budget


class DailyBudget:
    """Hard stop on LLM calls per day and process, well under free-tier quotas. The
    rule engine is free, so hitting the cap degrades to rules instead of failing."""

    def __init__(self) -> None:
        self.day: date | None = None
        self.used = 0

    def take(self, limit: int) -> bool:
        today = datetime.now(UTC).date()
        if self.day != today:
            self.day, self.used = today, 0
        if self.used >= limit:
            return False
        self.used += 1
        return True


def status(settings: Settings, provider: LLMProvider | None) -> AiStatus:
    enabled = settings.llm_provider != "none"
    return AiStatus(
        enabled=enabled,
        provider=settings.llm_provider,
        model=provider.model if provider else ("rules-v1" if enabled else None),
        features=["triage", "duplicates", "summary", "postmortem", "nl_search"] if enabled else [],
    )


def require_enabled(settings: Settings) -> None:
    if settings.llm_provider == "none":
        raise AiDisabled("AI assistance is turned off (LLM_PROVIDER=none)")


async def _ask[R: BaseModel](
    provider: LLMProvider | None,
    budget: DailyBudget,
    settings: Settings,
    prompt: Prompt,
    schema: type[R],
    feature: str,
) -> tuple[Completion[R] | None, str | None]:
    """(completion, None) from the model, or (None, why) meaning "use the rules"."""
    if provider is None:
        return None, None  # rules mode: not a fallback, the configured engine
    if not budget.take(settings.ai_daily_limit):
        log.warning("ai_budget_exhausted", feature=feature)
        return None, "daily AI budget reached"
    try:
        completion = await provider.complete(prompt, schema)
    except AIUnavailable as exc:
        log.warning("ai_unavailable", feature=feature, provider=provider.name, error=str(exc))
        return None, "AI unavailable"
    except InvalidOutput as exc:
        log.warning("ai_invalid_output", feature=feature, provider=provider.name, error=str(exc))
        return None, "AI returned an invalid answer"
    log.info(
        "ai_call",
        feature=feature,
        provider=provider.name,
        model=completion.model,
        prompt_version=prompt.version,
        latency_ms=completion.latency_ms,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
    )
    return completion, None


def _store(
    session: AsyncSession,
    *,
    actor: User,
    kind: SuggestionKind,
    payload: dict[str, Any],
    completion: Completion[Any] | None,
    prompt_version: str,
    started: float,
    incident_id: uuid.UUID | None = None,
) -> AiSuggestion:
    suggestion = AiSuggestion(
        id=uuid.uuid4(),
        incident_id=incident_id,
        user_id=actor.id,
        team_id=actor.active_team_id,
        kind=kind,
        payload=payload,
        source="llm" if completion else "rules",
        model=completion.model if completion else "rules-v1",
        prompt_version=prompt_version if completion else "rules-v1",
        latency_ms=completion.latency_ms
        if completion
        else int((time.perf_counter() - started) * 1000),
        tokens_in=completion.tokens_in if completion else 0,
        tokens_out=completion.tokens_out if completion else 0,
    )
    session.add(suggestion)
    return suggestion


def _similar_out(s: Similar) -> SimilarIncident:
    return SimilarIncident(
        id=s.id, key=s.key, title=s.title, status=s.status, priority=s.priority, score=s.score
    )


# ---------------------------------------------------------------- triage


async def triage(
    session: AsyncSession,
    settings: Settings,
    provider: LLMProvider | None,
    budget: DailyBudget,
    actor: User,
    title: str,
    description: str,
) -> TriageSuggestion:
    started = time.perf_counter()
    team_id = team_id_of(actor)
    similar = await find_similar_incidents(session, title, team_id=team_id)
    workload = await get_assignee_workload(session, team_id)
    team = {w.user_id: w for w in workload}

    prompt = prompts.triage(title, description, workload, similar, settings.ai_max_input_chars)
    completion, fallback = await _ask(provider, budget, settings, prompt, TriageOutput, "triage")

    if completion:
        out = completion.value
        assignee_id = out.suggested_assignee_id
        if assignee_id is not None and assignee_id not in team:
            # Hallucinated or not assignable: never shown (spec 10.3).
            log.warning("ai_hallucinated_assignee", assignee_id=str(assignee_id))
            assignee_id = None
        category = (out.category or "").lower() or None
        if category not in rules.CATEGORIES:
            category = None
        kept = {r.id for r in out.similar}
        shown = [s for s in similar if s.id in kept] or similar
        priority, confidence, reasoning = out.priority, out.confidence, out.reasoning
    else:
        r = rules.triage(title, description, workload, similar)
        priority, category, confidence, reasoning = (
            r.priority,
            r.category,
            r.confidence,
            r.reasoning,
        )
        assignee_id = uuid.UUID(r.suggested_assignee_id) if r.suggested_assignee_id else None
        shown = similar

    users = {
        u.id: u for u in (await session.scalars(select(User).where(User.id.in_(list(team))))).all()
    }
    assignee = (
        SuggestedAssignee(
            user=UserPublic.model_validate(users[assignee_id]),
            open_count=team[assignee_id].open_count,
        )
        if assignee_id and assignee_id in users
        else None
    )
    top = similar[0] if similar else None
    duplicate = _similar_out(top) if top and top.score > DUPLICATE_THRESHOLD else None

    result = TriageSuggestion(
        suggestion_id=uuid.uuid4(),
        source="llm" if completion else "rules",
        model=completion.model if completion else "rules-v1",
        priority=priority,
        category=category,
        assignee=assignee,
        confidence=round(confidence, 2),
        reasoning=reasoning,
        similar=[_similar_out(s) for s in shown[:5]],
        possible_duplicate_of=duplicate,
        fallback_reason=fallback,
    )
    stored = _store(
        session,
        actor=actor,
        kind=SuggestionKind.TRIAGE,
        payload=result.model_dump(mode="json", exclude={"suggestion_id"}),
        completion=completion,
        prompt_version=prompt.version,
        started=started,
    )
    await session.commit()
    return result.model_copy(update={"suggestion_id": stored.id})


# ---------------------------------------------------------------- summary / postmortem


def _event_text(e: IncidentEvent) -> str:
    who = e.actor.name.split()[0] if e.actor else "System"
    nv, ov = e.new_value, e.old_value

    def name(v: Any) -> str:
        return str(v.get("name", "someone")).split()[0] if isinstance(v, dict) else "someone"

    match e.event_type:
        case EventType.CREATED:
            text = f"{who} reported the task"
        case EventType.STATUS_CHANGED:
            text = f"{who} moved it {ov} -> {nv}"
        case EventType.ASSIGNED:
            text = f"{who} assigned {name(nv)}"
        case EventType.UNASSIGNED:
            text = f"{who} unassigned {name(ov)}"
        case EventType.PRIORITY_CHANGED:
            p = nv.get("priority") if isinstance(nv, dict) else nv
            text = f"{who} changed priority to {p}"
        case EventType.COMMENTED:
            text = f"{who} commented"
        case EventType.SLA_BREACHED:
            text = "The resolution SLA was breached"
        case _:
            text = f"{who}: {e.event_type.value.replace('_', ' ')}"
    return text + (f" ({e.note})" if e.note else "")


async def summarize(
    session: AsyncSession,
    settings: Settings,
    provider: LLMProvider | None,
    budget: DailyBudget,
    actor: User,
    raw_ident: str,
    kind: str,
) -> SummarySuggestion:
    started = time.perf_counter()
    incident = await incident_service.get(session, actor, raw_ident)
    if kind == "postmortem" and incident.status not in (Status.RESOLVED, Status.CLOSED):
        raise Conflict("A postmortem needs a resolved task", code="not_resolved")
    # Visibility-checked: viewers' summaries never include internal notes.
    comments = await comment_service.list_for(session, actor, raw_ident)
    events = await incident_repo.list_events(session, incident.id)
    key = key_for(incident.number)
    now = utcnow()

    thread = [
        rules.ThreadItem(author=c.author.name.split()[0], body=c.body, created_at=c.created_at)
        for c in comments
    ]
    timeline = [
        rules.TimelineItem(at=e.created_at, text=_event_text(e))
        for e in events
        if e.event_type not in TIMELINE_NOISE
    ]
    resolution_note = next(
        (
            e.note
            for e in reversed(events)
            if e.event_type == EventType.STATUS_CHANGED and e.new_value == "resolved" and e.note
        ),
        None,
    )
    context = truncate(
        "\n".join(
            [
                f"Key: {key}",
                f"Title: {incident.title}",
                f"Priority: {incident.priority.value}; status: {incident.status.value}; "
                f"category: {incident.category or 'none'}",
                f"Assignee: {incident.assignee.name if incident.assignee else 'nobody'}",
                f"Description: {incident.description}",
                "Timeline:",
                *[f"- {t.at:%Y-%m-%d %H:%M} {t.text}" for t in timeline],
                "Comments:",
                *[f"- {t.author} ({t.created_at:%H:%M}): {t.body}" for t in thread],
                f"Resolution note: {resolution_note or 'none'}",
            ]
        ),
        settings.ai_max_input_chars,
    )

    if kind == "postmortem":
        prompt = prompts.postmortem(context)
        pm_completion, fallback = await _ask(
            provider, budget, settings, prompt, PostmortemOutput, "postmortem"
        )
        if pm_completion:
            pm = pm_completion.value
        else:
            breached = presenters.sla_state(incident, now).resolution_breached
            pm = PostmortemOutput.model_validate(
                rules.postmortem(
                    key=key,
                    title=incident.title,
                    priority=incident.priority,
                    category=incident.category,
                    created_at=incident.created_at,
                    resolved_at=incident.resolved_at,
                    resolution_note=resolution_note,
                    breached=breached,
                    timeline=timeline,
                )
            )
        markdown = rules.postmortem_markdown(key, incident.title, pm.model_dump())
        result = SummarySuggestion(
            suggestion_id=uuid.uuid4(),
            kind="postmortem",
            source="llm" if pm_completion else "rules",
            model=pm_completion.model if pm_completion else "rules-v1",
            postmortem=pm,
            markdown=markdown,
            fallback_reason=fallback,
        )
        completion: Completion[Any] | None = pm_completion
        suggestion_kind = SuggestionKind.POSTMORTEM
    else:
        prompt = prompts.summary(context)
        sm_completion, fallback = await _ask(
            provider, budget, settings, prompt, SummaryOutput, "summary"
        )
        sm = (
            sm_completion.value
            if sm_completion
            else SummaryOutput.model_validate(
                rules.summarize(
                    key=key,
                    title=incident.title,
                    status=incident.status,
                    priority=incident.priority,
                    assignee=incident.assignee.name if incident.assignee else None,
                    comments=thread,
                    now=now,
                )
            )
        )
        result = SummarySuggestion(
            suggestion_id=uuid.uuid4(),
            kind="summary",
            source="llm" if sm_completion else "rules",
            model=sm_completion.model if sm_completion else "rules-v1",
            summary=sm,
            fallback_reason=fallback,
        )
        completion = sm_completion
        suggestion_kind = SuggestionKind.SUMMARY

    stored = _store(
        session,
        actor=actor,
        kind=suggestion_kind,
        payload=result.model_dump(mode="json", exclude={"suggestion_id"}),
        completion=completion,
        prompt_version=prompt.version,
        started=started,
        incident_id=incident.id,
    )
    await session.commit()
    return result.model_copy(update={"suggestion_id": stored.id})


# ---------------------------------------------------------------- natural-language search


def _explain(f: SearchOutput, names: dict[str, str]) -> str:
    parts: list[str] = []
    if f.priority:
        parts.append(" or ".join(p.value for p in f.priority))
    if f.status:
        parts.append(" or ".join(s.value.replace("_", " ") for s in f.status))
    parts.append("incidents")
    if f.assignee == "me":
        parts.append("assigned to you")
    elif f.assignee == "none":
        parts.append("with nobody assigned")
    elif f.assignee:
        parts.append(f"assigned to {names.get(f.assignee, 'someone')}")
    if f.sla == "breached":
        parts.append("past their SLA")
    elif f.sla == "at_risk":
        parts.append("at risk of breaching")
    if f.q:
        parts.append(f'matching "{f.q}"')
    text = " ".join(parts)
    return text[:1].upper() + text[1:]  # not .capitalize(): it would lower-case "SLA"


async def nl_search(
    session: AsyncSession,
    settings: Settings,
    provider: LLMProvider | None,
    budget: DailyBudget,
    actor: User,
    query: str,
) -> SearchSuggestion:
    started = time.perf_counter()
    workload = await get_assignee_workload(session, team_id_of(actor))
    team = [(str(w.user_id), w.name) for w in workload]
    names = {uid: name.split()[0] for uid, name in team}

    prompt = prompts.search(query, [(uid, name.split()[0]) for uid, name in team])
    completion, fallback = await _ask(provider, budget, settings, prompt, SearchOutput, "nl_search")
    filters = (
        completion.value
        if completion
        else SearchOutput.model_validate(rules.nl_search(query, team))
    )
    if filters.assignee not in (None, "me", "none") and filters.assignee not in names:
        log.warning("ai_hallucinated_assignee", assignee=filters.assignee)
        filters = filters.model_copy(update={"assignee": None})

    result = SearchSuggestion(
        suggestion_id=uuid.uuid4(),
        source="llm" if completion else "rules",
        model=completion.model if completion else "rules-v1",
        filters=filters,
        explanation=_explain(filters, names),
        fallback_reason=fallback,
    )
    stored = _store(
        session,
        actor=actor,
        kind=SuggestionKind.NL_SEARCH,
        payload={"query": query, **result.model_dump(mode="json", exclude={"suggestion_id"})},
        completion=completion,
        prompt_version=prompt.version,
        started=started,
    )
    await session.commit()
    return result.model_copy(update={"suggestion_id": stored.id})


# ---------------------------------------------------------------- decisions


async def _own_pending(
    session: AsyncSession, actor: User, suggestion_id: uuid.UUID
) -> AiSuggestion:
    suggestion = await session.get(AiSuggestion, suggestion_id, with_for_update=True)
    if suggestion is None or suggestion.user_id != actor.id:
        raise NotFound("Suggestion not found")
    if suggestion.status != SuggestionStatus.PENDING:
        raise Conflict("This suggestion was already decided", code="already_decided")
    return suggestion


async def accept(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    suggestion_id: uuid.UUID,
    body: AcceptRequest,
) -> AiSuggestion:
    suggestion = await _own_pending(session, actor, suggestion_id)
    payload = suggestion.payload

    if suggestion.kind == SuggestionKind.TRIAGE and body.incident:
        # Applied through the normal services: permission checks and audit included.
        changes: dict[str, Any] = {}
        if "priority" in body.apply and payload.get("priority"):
            changes["priority"] = payload["priority"]
        if "category" in body.apply and payload.get("category"):
            changes["category"] = payload["category"]
        incident = await incident_service.get(session, actor, body.incident)
        suggestion.incident_id = incident.id
        if changes:
            await incident_service.update(
                session, settings, actor, body.incident, IncidentUpdate.model_validate(changes)
            )
        assignee = payload.get("assignee") or {}
        if "assignee" in body.apply and assignee.get("user"):
            await incident_service.assign(
                session, settings, actor, body.incident, uuid.UUID(assignee["user"]["id"])
            )
        incident = await incident_service.load_live(session, incident.id, actor)
        incident_service.record_event(
            session,
            incident,
            actor,
            EventType.AI_APPLIED,
            field="ai_suggestion",
            new={"id": str(suggestion.id), "kind": "triage", "applied": body.apply},
        )
    elif suggestion.kind == SuggestionKind.POSTMORTEM:
        markdown = (body.markdown or payload.get("markdown") or "").strip()
        if not markdown or suggestion.incident_id is None:
            raise InvalidInput("Nothing to post", code="empty_postmortem")
        incident = await incident_service.get(session, actor, str(suggestion.incident_id))
        await comment_service.add(
            session,
            settings,
            actor,
            key_for(incident.number),
            body=markdown,
            is_internal=True,
        )

    suggestion = (
        await session.get(AiSuggestion, suggestion_id, populate_existing=True) or suggestion
    )
    suggestion.status = SuggestionStatus.ACCEPTED
    suggestion.decided_at = utcnow()
    await session.commit()
    return suggestion


async def reject(session: AsyncSession, actor: User, suggestion_id: uuid.UUID) -> AiSuggestion:
    suggestion = await _own_pending(session, actor, suggestion_id)
    suggestion.status = SuggestionStatus.REJECTED
    suggestion.decided_at = utcnow()
    await session.commit()
    return suggestion


async def stats(session: AsyncSession, team_id: uuid.UUID) -> dict[str, Any]:
    """Accept rate, source split and latency per feature in one team, for its admins."""
    rows = (
        await session.execute(
            select(
                AiSuggestion.kind,
                AiSuggestion.status,
                AiSuggestion.source,
                func.count(),
                func.avg(AiSuggestion.latency_ms),
            )
            .where(AiSuggestion.team_id == team_id)
            .group_by(AiSuggestion.kind, AiSuggestion.status, AiSuggestion.source)
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for kind, st, source, count, latency in rows:
        k = out.setdefault(
            kind.value, {"total": 0, "accepted": 0, "rejected": 0, "llm": 0, "rules": 0, "_lat": []}
        )
        k["total"] += count
        k[source] += count
        if st != SuggestionStatus.PENDING:
            k[st.value] += count
        k["_lat"].append((float(latency or 0), count))
    for k in out.values():
        pairs = k.pop("_lat")
        n = sum(c for _, c in pairs)
        k["avg_latency_ms"] = round(sum(latency * c for latency, c in pairs) / n) if n else 0
        decided = k["accepted"] + k["rejected"]
        k["accept_rate"] = round(k["accepted"] / decided, 2) if decided else None
    return out

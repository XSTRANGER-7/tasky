"""/api/v1/incidents -- HTTP only. Rules: services/incident_service.py, permissions.py."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status
from pydantic import BaseModel, Field

from app.core.deps import AppSettings, DbSession, TeamUser
from app.db.base import utcnow
from app.models import Incident, Priority, Status
from app.repositories import incident_repo
from app.schemas.incident import (
    AssignIn,
    CommentCreate,
    CommentOut,
    EventOut,
    IncidentCreate,
    IncidentOut,
    IncidentUpdate,
    TransitionIn,
)
from app.services import (
    comment_service,
    incident_query,
    incident_service,
    presenters,
    watch_service,
)
from app.services import permissions as perms

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

Ident = Annotated[str, "UUID or human key such as INC-142"]
IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        max_length=100,
        description="Retries with the same key return the original incident instead of "
        "creating a duplicate.",
    ),
]


class IncidentPage(BaseModel):
    items: list[IncidentOut]
    next_cursor: str | None
    total: int


async def _out(session: DbSession, actor: TeamUser, incident: Incident) -> IncidentOut:
    counts = await incident_repo.comment_counts(
        session, [incident.id], include_internal=perms.can_see_internal(actor)
    )
    watchers = await watch_service.watchers_for(session, [incident.id])
    assigned_by = (
        await incident_repo.last_assigner(session, incident.id) if incident.assignee_id else None
    )
    return presenters.incident_out(
        incident,
        actor,
        utcnow(),
        comment_count=counts.get(incident.id, 0),
        watchers=watchers.get(incident.id, []),
        assigned_by=assigned_by,
    )


@router.get("", response_model=IncidentPage, summary="List and search incidents")
async def list_incidents(
    session: DbSession,
    actor: TeamUser,
    status_: Annotated[list[Status], Query(alias="status")] = [],  # noqa: B006
    priority: Annotated[list[Priority], Query()] = [],  # noqa: B006
    assignee: Annotated[list[str], Query(description="User id, `me` or `none`; repeatable")] = [],  # noqa: B006
    reporter: Annotated[str | None, Query(description="User id or `me`")] = None,
    q: Annotated[
        str | None,
        Query(max_length=200, description="Full-text + fuzzy title search; `INC-142` too"),
    ] = None,
    sla: Annotated[incident_query.SlaFilter | None, Query()] = None,
    category: Annotated[str | None, Query(max_length=50)] = None,
    tag: Annotated[list[str], Query(description="All given tags must match")] = [],  # noqa: B006
    deleted: Annotated[bool, Query(description="Admins: list the recycle bin")] = False,
    watching: Annotated[bool, Query(description="Only incidents I watch")] = False,
    sort: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Comma-separated, `-` = descending. Allowed: created_at, updated_at, "
            "priority, status, number, resolution_due_at, relevance (needs q). "
            "Default: -created_at, or relevance when q is given.",
        ),
    ] = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> IncidentPage:
    filters = incident_query.IncidentFilters(
        status=status_,
        priority=priority,
        assignee=assignee,
        reporter=reporter,
        q=q,
        sla=sla,
        category=category,
        tags=tag,
        deleted=deleted,
        watching=watching,
    )
    page = await incident_query.search(
        session, actor, filters, sort=sort, cursor=cursor, limit=limit
    )
    ids = [i.id for i in page.items]
    counts = await incident_repo.comment_counts(
        session, ids, include_internal=perms.can_see_internal(actor)
    )
    watchers = await watch_service.watchers_for(session, ids)
    now = utcnow()
    return IncidentPage(
        items=[
            presenters.incident_out(
                i, actor, now, comment_count=counts.get(i.id, 0), watchers=watchers.get(i.id, [])
            )
            for i in page.items
        ],
        next_cursor=page.next_cursor,
        total=page.total,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=IncidentOut,
    summary="Create an incident",
    description="The current user is the reporter. SLA due times are set from the priority.",
)
async def create_incident(
    body: IncidentCreate,
    response: Response,
    session: DbSession,
    settings: AppSettings,
    actor: TeamUser,
    idempotency_key: IdempotencyKeyHeader = None,
) -> IncidentOut:
    incident, created = await incident_service.create(
        session, settings, actor, body, idempotency_key=idempotency_key
    )
    if not created:
        response.headers["Idempotent-Replayed"] = "true"
    return await _out(session, actor, incident)


@router.get("/{ident}", response_model=IncidentOut, summary="Get an incident by id or INC-key")
async def get_incident(ident: Ident, session: DbSession, actor: TeamUser) -> IncidentOut:
    return await _out(session, actor, await incident_service.get(session, actor, ident))


@router.patch("/{ident}", response_model=IncidentOut, summary="Update fields (audited)")
async def update_incident(
    ident: Ident,
    body: IncidentUpdate,
    session: DbSession,
    settings: AppSettings,
    actor: TeamUser,
) -> IncidentOut:
    incident = await incident_service.update(session, settings, actor, ident, body)
    return await _out(session, actor, incident)


@router.post(
    "/{ident}/assign",
    response_model=IncidentOut,
    summary="Assign to one person, or unassign",
    description="Replaces every assignee with this one person (null: nobody). "
    "Use PUT /assignees to assign several people.",
)
async def assign_incident(
    ident: Ident, body: AssignIn, session: DbSession, settings: AppSettings, actor: TeamUser
) -> IncidentOut:
    incident = await incident_service.assign(session, settings, actor, ident, body.assignee_id)
    return await _out(session, actor, incident)


class AssigneesIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(max_length=10, description="In order; the first leads")


@router.put(
    "/{ident}/assignees",
    response_model=IncidentOut,
    summary="Set everyone assigned",
    description="The full list, in order (the first is the lead). People newly on the list "
    "are emailed; an empty list unassigns everyone (not while in progress).",
)
async def set_assignees(
    ident: Ident, body: AssigneesIn, session: DbSession, settings: AppSettings, actor: TeamUser
) -> IncidentOut:
    incident = await incident_service.set_assignees(session, settings, actor, ident, body.user_ids)
    return await _out(session, actor, incident)


@router.post(
    "/{ident}/transition",
    response_model=IncidentOut,
    summary="Move through the lifecycle",
    description="409 if the move is not allowed from the current status, 403 if you may "
    "not make it, 422 when starting work without an assignee.",
)
async def transition_incident(
    ident: Ident,
    body: TransitionIn,
    session: DbSession,
    settings: AppSettings,
    actor: TeamUser,
) -> IncidentOut:
    incident = await incident_service.transition(
        session, settings, actor, ident, body.status, body.note
    )
    return await _out(session, actor, incident)


@router.delete("/{ident}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft-delete (admin)")
async def delete_incident(ident: Ident, session: DbSession, actor: TeamUser) -> Response:
    await incident_service.delete(session, actor, ident)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{ident}/restore", response_model=IncidentOut, summary="Restore (team admins)")
async def restore_incident(ident: Ident, session: DbSession, actor: TeamUser) -> IncidentOut:
    return await _out(session, actor, await incident_service.restore(session, actor, ident))


@router.get("/{ident}/events", response_model=list[EventOut], summary="Audit timeline")
async def list_events(ident: Ident, session: DbSession, actor: TeamUser) -> list[EventOut]:
    incident = await incident_service.get(session, actor, ident)
    events = await incident_repo.list_events(session, incident.id)
    hide_internal = not perms.can_see_internal(actor)
    return [
        presenters.event_out(e)
        for e in events
        if not (hide_internal and isinstance(e.new_value, dict) and e.new_value.get("internal"))
    ]


@router.get("/{ident}/comments", response_model=list[CommentOut], summary="Comment thread")
async def list_comments(ident: Ident, session: DbSession, actor: TeamUser) -> list[CommentOut]:
    now = utcnow()
    return [
        presenters.comment_out(c, actor, now)
        for c in await comment_service.list_for(session, actor, ident)
    ]


@router.post(
    "/{ident}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentOut,
    summary="Add a comment (Markdown)",
)
async def add_comment(
    ident: Ident, body: CommentCreate, session: DbSession, settings: AppSettings, actor: TeamUser
) -> CommentOut:
    comment = await comment_service.add(
        session, settings, actor, ident, body=body.body, is_internal=body.is_internal
    )
    return presenters.comment_out(comment, actor, utcnow())


@router.post(
    "/{ident}/watch",
    response_model=IncidentOut,
    summary="Watch an incident",
    description="Watchers are notified about assignment, resolution and new comments. Idempotent.",
)
async def watch_incident(ident: Ident, session: DbSession, actor: TeamUser) -> IncidentOut:
    await watch_service.watch(session, actor, ident)
    return await _out(session, actor, await incident_service.get(session, actor, ident))


class AddPersonIn(BaseModel):
    user_id: uuid.UUID


@router.post(
    "/{ident}/watchers",
    response_model=IncidentOut,
    summary="Add a teammate to a task (team admins)",
    description="They follow it from now on and are emailed that they were added. "
    "Only the team's admins can add other people (anyone can follow a task themself with "
    "POST /watch); the person must be in the task's team. Idempotent.",
)
async def add_person(
    ident: Ident, body: AddPersonIn, session: DbSession, settings: AppSettings, actor: TeamUser
) -> IncidentOut:
    await watch_service.add_person(session, settings, actor, ident, body.user_id)
    return await _out(session, actor, await incident_service.get(session, actor, ident))


@router.delete(
    "/{ident}/watchers/{user_id}",
    response_model=IncidentOut,
    summary="Remove someone from a task",
    description="Yourself always; anyone else only if you are a team admin.",
)
async def remove_person(
    ident: Ident, user_id: uuid.UUID, session: DbSession, actor: TeamUser
) -> IncidentOut:
    await watch_service.remove_person(session, actor, ident, user_id)
    return await _out(session, actor, await incident_service.get(session, actor, ident))


@router.delete(
    "/{ident}/watch",
    response_model=IncidentOut,
    summary="Stop watching an incident",
)
async def unwatch_incident(ident: Ident, session: DbSession, actor: TeamUser) -> IncidentOut:
    await watch_service.unwatch(session, actor, ident)
    return await _out(session, actor, await incident_service.get(session, actor, ident))

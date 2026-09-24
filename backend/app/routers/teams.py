"""/api/v1/teams -- create, discover, join, and manage teams. HTTP only; every rule lives
in services/team_service.py."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.deps import AppSettings, CurrentUser, DbSession
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.models import JoinRequestStatus, TeamJoinRequest, TeamMembership, User
from app.repositories import team_repo
from app.schemas.team import (
    DecisionIn,
    JoinRequestIn,
    JoinRequestOut,
    MemberAdd,
    MemberOut,
    MemberRoleIn,
    MyTeams,
    TeamBrief,
    TeamCreate,
    TeamOut,
    TeamUpdate,
)
from app.schemas.user import TeamPerson, UserPublic
from app.services import team_service
from app.services.team_service import TeamView
from app.storage import LocalStorage, S3Storage, StorageError

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/teams", tags=["teams"])


# ---------------------------------------------------------------- presenters


def team_out(view: TeamView) -> TeamOut:
    t = view.team
    return TeamOut(
        id=t.id,
        name=t.name,
        slug=t.slug,
        description=t.description,
        created_at=t.created_at,
        member_count=view.member_count,
        my_role=view.my_role,
        pending_request_id=view.pending_request_id,
    )


def member_out(user: User, membership: TeamMembership) -> MemberOut:
    return MemberOut(
        user=TeamPerson(
            **UserPublic.model_validate(user).model_dump(), role=membership.role.as_role()
        ),
        role=membership.role,
        is_active=user.is_active,
        joined_at=membership.created_at,
    )


def request_out(r: TeamJoinRequest) -> JoinRequestOut:
    return JoinRequestOut(
        id=r.id,
        team=TeamBrief.model_validate(r.team),
        user=UserPublic.model_validate(r.user),
        message=r.message,
        status=r.status,
        granted_role=r.granted_role,
        decided_by=UserPublic.model_validate(r.decided_by) if r.decided_by else None,
        decided_at=r.decided_at,
        created_at=r.created_at,
    )


async def _reload(session: DbSession, request_id: uuid.UUID) -> JoinRequestOut:
    """Read a request back with its team, requester and decider loaded."""
    session.expunge_all()  # drop stale identity-map rows from the write above
    row = await team_repo.get_request(session, request_id)
    assert row is not None  # noqa: S101 - just written in this request
    return request_out(row)


# ---------------------------------------------------------------- mine / discover


@router.get("/mine", response_model=MyTeams, summary="My teams and my join requests")
async def mine(session: DbSession, actor: CurrentUser) -> MyTeams:
    teams = await team_service.my_teams(session, actor)
    requests = await team_service.my_requests(session, actor)
    return MyTeams(teams=[team_out(v) for v in teams], requests=[request_out(r) for r in requests])


@router.get(
    "/discover",
    response_model=list[TeamOut],
    summary="Find teams to join",
    description="Every team matching `q` (name or slug), with your role or open request.",
)
async def discover(
    session: DbSession,
    actor: CurrentUser,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> list[TeamOut]:
    return [team_out(v) for v in await team_service.discover(session, actor, q)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TeamOut,
    summary="Create a team (you become its admin)",
    dependencies=[Depends(rate_limit("create_team", lambda s: 10))],
)
async def create_team(body: TeamCreate, session: DbSession, actor: CurrentUser) -> TeamOut:
    team = await team_service.create_team(
        session, actor, name=body.name, description=body.description
    )
    return team_out(await team_service.get_team(session, actor, team.id))


@router.get("/{team_id}", response_model=TeamOut, summary="A team you belong to")
async def get_team(team_id: uuid.UUID, session: DbSession, actor: CurrentUser) -> TeamOut:
    return team_out(await team_service.get_team(session, actor, team_id))


@router.patch("/{team_id}", response_model=TeamOut, summary="Rename or describe (team admins)")
async def update_team(
    team_id: uuid.UUID, body: TeamUpdate, session: DbSession, actor: CurrentUser
) -> TeamOut:
    await team_service.update_team(
        session, actor, team_id, name=body.name, description=body.description
    )
    return team_out(await team_service.get_team(session, actor, team_id))


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the team and all its incidents (team admins)",
)
async def delete_team(
    team_id: uuid.UUID, request: Request, session: DbSession, actor: CurrentUser
) -> Response:
    keys = await team_service.delete_team(session, actor, team_id)
    storage: LocalStorage | S3Storage = request.app.state.storage
    for key in keys:  # rows are gone; a stray blob is harmless, so failures only log
        try:
            await storage.delete(key)
        except StorageError as exc:
            log.warning("attachment_blob_delete_failed", key=key, error=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- members


@router.get("/{team_id}/members", response_model=list[MemberOut], summary="Members")
async def list_members(
    team_id: uuid.UUID, session: DbSession, actor: CurrentUser
) -> list[MemberOut]:
    return [member_out(u, m) for u, m in await team_service.members(session, actor, team_id)]


@router.post(
    "/{team_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberOut,
    summary="Add an existing account (team admins)",
)
async def add_member(
    team_id: uuid.UUID,
    body: MemberAdd,
    session: DbSession,
    settings: AppSettings,
    actor: CurrentUser,
) -> MemberOut:
    user, membership = await team_service.add_member(
        session, settings, actor, team_id, email=body.email, role=body.role
    )
    return member_out(user, membership)


@router.patch(
    "/{team_id}/members/{user_id}",
    response_model=MemberOut,
    summary="Change a member's team role",
    description="Team admins. The last admin cannot be demoted (409 `last_admin`).",
)
async def change_role(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRoleIn,
    session: DbSession,
    settings: AppSettings,
    actor: CurrentUser,
) -> MemberOut:
    membership = await team_service.change_role(
        session, settings, actor, team_id, user_id, body.role
    )
    user = await session.get(User, user_id)
    assert user is not None  # noqa: S101 - a membership implies the user exists
    return member_out(user, membership)


@router.delete(
    "/{team_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member, or leave (your own id)",
)
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    session: DbSession,
    settings: AppSettings,
    actor: CurrentUser,
) -> Response:
    await team_service.remove_member(session, settings, actor, team_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- join requests


@router.post(
    "/{team_id}/join-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=JoinRequestOut,
    summary="Ask to join a team",
    description="Emails the team's admins and shows them the request in the app. "
    "Asking again while a request is open returns the same request.",
    dependencies=[Depends(rate_limit("join_request", lambda s: 10))],
)
async def request_to_join(
    team_id: uuid.UUID,
    body: JoinRequestIn,
    session: DbSession,
    settings: AppSettings,
    actor: CurrentUser,
) -> JoinRequestOut:
    request = await team_service.request_to_join(
        session, settings, actor, team_id, message=body.message
    )
    return await _reload(session, request.id)


@router.get(
    "/{team_id}/join-requests",
    response_model=list[JoinRequestOut],
    summary="A team's join requests (team admins)",
)
async def team_requests(
    team_id: uuid.UUID,
    session: DbSession,
    actor: CurrentUser,
    status_: Annotated[JoinRequestStatus | None, Query(alias="status")] = None,
) -> list[JoinRequestOut]:
    rows = await team_service.requests_for_team(session, actor, team_id, status_)
    return [request_out(r) for r in rows]


@router.get(
    "/join-requests/review",
    response_model=list[JoinRequestOut],
    summary="Pending requests I can decide",
    description="Every team you are an admin of.",
)
async def to_review(session: DbSession, actor: CurrentUser) -> list[JoinRequestOut]:
    return [request_out(r) for r in await team_service.requests_to_review(session, actor)]


@router.post(
    "/join-requests/{request_id}/approve",
    response_model=JoinRequestOut,
    summary="Approve, choosing the new member's role",
)
async def approve(
    request_id: uuid.UUID,
    session: DbSession,
    settings: AppSettings,
    actor: CurrentUser,
    body: DecisionIn | None = None,
) -> JoinRequestOut:
    role = (body or DecisionIn()).role
    await team_service.decide(session, settings, actor, request_id, approve=True, role=role)
    return await _reload(session, request_id)


@router.post("/join-requests/{request_id}/reject", response_model=JoinRequestOut, summary="Reject")
async def reject(
    request_id: uuid.UUID, session: DbSession, settings: AppSettings, actor: CurrentUser
) -> JoinRequestOut:
    await team_service.decide(session, settings, actor, request_id, approve=False)
    return await _reload(session, request_id)


@router.post(
    "/join-requests/{request_id}/cancel",
    response_model=JoinRequestOut,
    summary="Withdraw my own request",
)
async def cancel(request_id: uuid.UUID, session: DbSession, actor: CurrentUser) -> JoinRequestOut:
    await team_service.cancel_request(session, actor, request_id)
    return await _reload(session, request_id)

"""Request-scoped dependencies shared by routers: DB session, current user, active team."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import InvalidInput, PermissionDenied, Unauthenticated
from app.db.session import get_session
from app.models import TeamRole, User
from app.repositories import team_repo
from app.services import auth_service

# auto_error=False: we raise our own 401 so it uses the standard error envelope.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")

DbSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def get_optional_user(
    session: DbSession, settings: AppSettings, credentials: Credentials
) -> User | None:
    if credentials is None:
        return None
    user = await auth_service.authenticate(session, settings, credentials.credentials)
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


async def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise Unauthenticated()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


TeamHeader = Annotated[
    str | None,
    Header(
        alias="X-Team-Id",
        description="The team to act in. Optional when you belong to exactly one team.",
    ),
]


async def get_team_user(user: CurrentUser, session: DbSession, team: TeamHeader = None) -> User:
    """The current user with their active team attached (``active_team_id`` and
    ``active_team_role``), for every route that reads or changes team data.

    * ``X-Team-Id`` picks the team; without it, a user in exactly one team acts there.
    * People act with their role in that team, and only in teams they belong to: there
      is no platform-wide admin who can reach into someone else's team.
    * No team at all -> 403 ``no_team`` (the SPA sends people to create or join one).
    """
    if team:
        try:
            team_id = uuid.UUID(team)
        except ValueError as exc:
            raise InvalidInput("X-Team-Id must be a team id", code="invalid_team") from exc
        membership = await team_repo.get_membership(session, team_id, user.id)
        if membership is None:
            raise PermissionDenied("You are not a member of this team", code="not_team_member")
        user.active_team_id = team_id
        user.active_team_role = membership.role
    else:
        teams = await team_repo.teams_of_user(session, user.id)
        if not teams:
            raise PermissionDenied("Create or join a team first", code="no_team")
        if len(teams) > 1:
            raise InvalidInput("You belong to several teams: send X-Team-Id", code="team_required")
        only, role = teams[0]
        user.active_team_id = only.id
        user.active_team_role = role
    structlog.contextvars.bind_contextvars(team_id=str(user.active_team_id))
    return user


TeamUser = Annotated[User, Depends(get_team_user)]


async def get_team_admin(user: TeamUser) -> User:
    """An admin of the active team: manages its people, requests, email and settings."""
    if user.active_team_role != TeamRole.ADMIN:
        raise PermissionDenied("Only team admins can do this", code="not_team_admin")
    return user


TeamAdmin = Annotated[User, Depends(get_team_admin)]

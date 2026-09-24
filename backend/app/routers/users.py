"""/api/v1/users -- the active team's directory, and your own profile."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Request, Response, status

from app.core.deps import CurrentUser, DbSession, TeamUser
from app.core.errors import NotFound
from app.routers.attachments import _read_body, _storage
from app.schemas.user import TeamPerson, TeamPersonFull, UserOut, UserPublic, UserUpdate
from app.services import avatar_service, user_service
from app.services import permissions as perms
from app.storage import StorageError

router = APIRouter(prefix="/api/v1/users", tags=["users"])
avatars = APIRouter(prefix="/api/v1/avatars", tags=["users"])


@router.get(
    "",
    response_model=list[TeamPersonFull] | list[TeamPerson],
    summary="List the team's people",
    description="Members of the active team (assignee picker), each with their role in "
    "this team. Team admins also see deactivated members and every field.",
)
async def list_users(
    session: DbSession, actor: TeamUser
) -> list[TeamPersonFull] | list[TeamPerson]:
    rows = await user_service.list_team_directory(session, actor)
    if perms.is_admin(actor):
        return [
            TeamPersonFull(**UserOut.model_validate(u).model_dump(), role=m.role.as_role())
            for u, m in rows
        ]
    return [
        TeamPerson(**UserPublic.model_validate(u).model_dump(), role=m.role.as_role())
        for u, m in rows
    ]


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="Update your profile",
    description="Your own name and email preference. Anyone else's profile is 403: there "
    "is no platform-wide admin.",
)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, session: DbSession, actor: CurrentUser
) -> UserOut:
    user = await user_service.update_user(session, actor, user_id, body)
    return UserOut.model_validate(user)


@router.put(
    "/me/avatar",
    response_model=UserOut,
    summary="Set your profile photo",
    description="Body: the raw image (PNG, JPEG or GIF, at most 2 MB; the type is "
    "detected from the content). Replaces any previous photo.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def set_avatar(request: Request, session: DbSession, actor: CurrentUser) -> UserOut:
    data = await _read_body(request, avatar_service.MAX_AVATAR_BYTES)
    user = await avatar_service.set_avatar(session, _storage(request), actor, data)
    return UserOut.model_validate(user)


@router.delete("/me/avatar", response_model=UserOut, summary="Remove your profile photo")
async def remove_avatar(request: Request, session: DbSession, actor: CurrentUser) -> UserOut:
    user = await avatar_service.remove_avatar(session, _storage(request), actor)
    return UserOut.model_validate(user)


@avatars.get(
    "/{name}",
    summary="A profile photo",
    description="Public, like avatars anywhere: the name is random and only reachable "
    "through a user record. Cached for a year; a new photo gets a new name.",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}, "image/gif": {}}}},
)
async def get_avatar(
    request: Request, name: Annotated[str, Path(pattern=avatar_service.NAME.pattern)]
) -> Response:
    try:
        data = await _storage(request).get(f"avatars/{name}")
    except StorageError as exc:
        raise NotFound("No such photo") from exc
    return Response(
        content=data,
        media_type=avatar_service.content_type_of(name),
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
        status_code=status.HTTP_200_OK,
    )

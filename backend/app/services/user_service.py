"""User rules.

* Anyone in a team may list its active members (assignee picker); team admins also see
  deactivated members. Everyone is listed with their role *in that team*.
* People change their own ``name`` and ``notify_email``. Accounts have no global role.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidInput, PermissionDenied
from app.core.logging import get_logger
from app.models import TeamMembership, User
from app.repositories import team_repo
from app.schemas.user import UserUpdate
from app.services import permissions as perms
from app.services.team_scope import team_id_of

log = get_logger(__name__)


async def list_team_directory(
    session: AsyncSession, actor: User
) -> Sequence[tuple[User, TeamMembership]]:
    return await team_repo.members(
        session, team_id_of(actor), include_inactive=perms.is_admin(actor)
    )


async def update_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, changes: UserUpdate
) -> User:
    """Everyone edits their own profile, and only their own: there is no platform admin.
    (Team admins manage who is in their team, not other people's accounts.)"""
    if user_id != actor.id:
        raise PermissionDenied("You can only edit your own profile")
    fields = changes.model_dump(exclude_unset=True)
    null_fields = sorted(k for k, v in fields.items() if v is None)
    if null_fields:
        raise InvalidInput("Fields cannot be null", details={"fields": null_fields})
    for key, value in fields.items():
        setattr(actor, key, value)
    await session.commit()
    log.info("user_updated", user_id=str(actor.id), fields=sorted(fields))
    return actor

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

from app.models import JoinRequestStatus, TeamRole
from app.schemas.user import TeamPerson, UserPublic

TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Message = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TeamBrief(_Out):
    id: uuid.UUID
    name: str
    slug: str


class TeamOut(TeamBrief):
    """A team as the caller sees it: their own role (if any) and any open request."""

    description: str
    created_at: datetime
    member_count: int
    my_role: TeamRole | None = None
    pending_request_id: uuid.UUID | None = None


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TeamName
    description: Description = ""


class TeamUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TeamName | None = None
    description: Description | None = None


class MemberOut(BaseModel):
    user: TeamPerson
    role: TeamRole
    is_active: bool
    joined_at: datetime


class MemberRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: TeamRole


class MemberAdd(BaseModel):
    """Add an existing account straight into the team (team admins)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: TeamRole = TeamRole.MEMBER


class JoinRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Message = ""


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: TeamRole = TeamRole.MEMBER


class JoinRequestOut(BaseModel):
    id: uuid.UUID
    team: TeamBrief
    user: UserPublic
    message: str
    status: JoinRequestStatus
    granted_role: TeamRole | None
    decided_by: UserPublic | None
    decided_at: datetime | None
    created_at: datetime


class MyTeams(BaseModel):
    """Everything the SPA needs after sign-in to pick a workspace or onboard."""

    teams: list[TeamOut]
    requests: list[JoinRequestOut]

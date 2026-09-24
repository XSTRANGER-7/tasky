from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models import Role

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# 8..128: long enough to matter, bounded so argon2 cannot be used for a CPU DoS.
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserPublic(_Out):
    """What any signed-in user may see about a teammate (avatars, names, mentions)."""

    id: uuid.UUID
    name: str
    email: EmailStr
    avatar_color: str
    avatar_url: str | None = None  # profile photo; None: show initials on avatar_color


class UserOut(UserPublic):
    """Full record: returned to the user themself and to admins."""

    is_active: bool
    notify_email: bool
    created_at: datetime
    onboarded: bool  # False until the first-sign-in page has been answered


class TeamPerson(UserPublic):
    """A member of the active team, with their role in it (the assignee picker)."""

    role: Role


class TeamPersonFull(UserOut):
    """The same, with every field: what the team's admins see."""

    role: Role


class ForgotPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    password: Password


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    email: EmailStr
    password: Password


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int = Field(description="Access-token lifetime in seconds")
    user: UserOut


class UserUpdate(BaseModel):
    """Your own profile. There is no global role to change: roles live in teams."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    notify_email: bool | None = None

"""User and refresh-token queries. Persistence only -- no decisions about what is allowed."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    # email is CITEXT, so this comparison is case-insensitive in the database.
    user: User | None = await session.scalar(select(User).where(User.email == email))
    return user


async def get_refresh_token_for_update(
    session: AsyncSession, token_hash: str
) -> RefreshToken | None:
    """Row-locked so two concurrent refreshes with the same token serialise."""
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    token: RefreshToken | None = await session.scalar(stmt)
    return token


async def revoke_all_refresh_tokens(
    session: AsyncSession, user_id: uuid.UUID, *, at: datetime
) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=at)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]

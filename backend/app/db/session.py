"""Async engine and session factory.

One engine per process, created lazily from settings so tests can point it elsewhere
before first use. ``pool_pre_ping`` survives Neon's idle auto-suspend, which silently
drops pooled connections.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_size,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None  # noqa: S101 - set together with the engine
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session (and transaction scope) per request."""
    async with get_sessionmaker()() as session:
        yield session


async def ping_database() -> None:
    """Raise if the database is unreachable. Used by /health."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None

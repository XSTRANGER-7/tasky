from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.main import create_app
from app.models import Role, Team, TeamMembership, TeamRole, User
from app.services.auth_service import avatar_color_for

if sys.platform == "win32":  # psycopg's async mode needs a selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_JWT_SECRET = "test-secret-test-secret-test-secret-00"
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/test"
)
PASSWORD = "correct-horse-battery"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked ``db`` need Postgres. CI sets REQUIRE_DB=1 so they can never be
    silently skipped there; locally they are skipped with a hint when no DB is set."""
    if os.environ.get("REQUIRE_DB") == "1" or os.environ.get("DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="set DATABASE_URL (or run `make up`) to run db tests")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        storage_dir=str(tmp_path / "attachments"),
        app_env="test",
        jwt_secret=TEST_JWT_SECRET,
        database_url=TEST_DATABASE_URL,
        metrics_enabled=True,
        log_json=True,
        git_sha="testsha",
        cookie_secure=False,  # the test client talks plain http://
        login_rate_limit_per_min=1000,  # rate limiting has its own tests
        register_rate_limit_per_min=1000,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------- database


@pytest.fixture(scope="session")
def _migrated() -> Iterator[None]:
    """Bring the test database to ``head`` once per run (sync: no event loop needed)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
async def db(_migrated: None, app: FastAPI) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory on the real test DB, also wired into the app. Every table is
    truncated afterwards so tests never see each other's rows."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE users, refresh_tokens, incidents, comments, incident_events, "
                    "idempotency_keys, notification_outbox, in_app_notifications, "
                    "incident_watchers, worker_heartbeats, attachments, ai_suggestions, "
                    "teams, team_memberships, team_join_requests, password_reset_tokens "
                    "RESTART IDENTITY CASCADE"
                )
            )
        await engine.dispose()


BuildApp = Callable[..., FastAPI]


@pytest.fixture
def build_app(settings: Settings, db: async_sessionmaker[AsyncSession]) -> BuildApp:
    """An extra app with some settings changed, wired to the same test database."""

    def _build(**overrides: object) -> FastAPI:
        extra = create_app(settings.model_copy(update=overrides))

        async def session_override() -> AsyncIterator[AsyncSession]:
            async with db() as session:
                yield session

        extra.dependency_overrides[get_session] = session_override
        return extra

    return _build


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


MakeUser = Callable[..., Awaitable[User]]

TEST_TEAM_SLUG = "test-team"
# Everyone made by ``make_user`` joins one shared team, and ``role`` is their role in it
# (accounts have no global role). The permission truth tables therefore run through the
# real team-scoped code paths.
TEAM_ROLE_FOR = {
    Role.ADMIN: TeamRole.ADMIN,
    Role.MEMBER: TeamRole.MEMBER,
    Role.VIEWER: TeamRole.VIEWER,
}


async def ensure_test_team(session: AsyncSession) -> Team:
    team = await session.scalar(select(Team).where(Team.slug == TEST_TEAM_SLUG))
    if team is None:
        team = Team(name="Test Team", slug=TEST_TEAM_SLUG)
        session.add(team)
        await session.flush()
    return team


@pytest.fixture
def make_user(db: async_sessionmaker[AsyncSession]) -> MakeUser:
    async def _make(
        email: str = "mira@example.com",
        *,
        role: Role = Role.MEMBER,
        name: str | None = None,
        password: str = PASSWORD,
        is_active: bool = True,
        team: bool = True,
    ) -> User:
        async with db() as session:
            user = User(
                name=name or email.split("@")[0].title(),
                email=email,
                password_hash=hash_password(password),
                is_active=is_active,
                avatar_color=avatar_color_for(email),
            )
            session.add(user)
            await session.flush()
            if team:
                shared = await ensure_test_team(session)
                session.add(
                    TeamMembership(team_id=shared.id, user_id=user.id, role=TEAM_ROLE_FOR[role])
                )
            await session.commit()
            return user

    return _make


Login = Callable[..., Awaitable[str]]


@pytest.fixture
def login(client: httpx.AsyncClient) -> Login:
    """Sign in through the API and return the access token."""

    async def _login(email: str, password: str = PASSWORD) -> str:
        res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        return str(res.json()["access_token"])

    return _login


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Person:
    """A seeded user plus ready-to-use auth headers (token minted directly: fast)."""

    def __init__(self, user: User, settings: Settings) -> None:
        self.user = user
        self.id = user.id
        self.headers = bearer(create_access_token(user.id, settings).token)


@pytest.fixture
async def people(make_user: MakeUser, settings: Settings) -> dict[str, Person]:
    specs = {
        "admin": ("ada@example.com", Role.ADMIN, "Ada Admin"),
        "mira": ("mira@example.com", Role.MEMBER, "Mira Member"),
        "max": ("max@example.com", Role.MEMBER, "Max Member"),
        "sam": ("sam@example.com", Role.VIEWER, "Sam Viewer"),
    }
    return {
        key: Person(await make_user(email, role=role, name=name), settings)
        for key, (email, role, name) in specs.items()
    }


CreateIncident = Callable[..., Awaitable[dict[str, object]]]


@pytest.fixture
def create_incident(client: httpx.AsyncClient, people: dict[str, Person]) -> CreateIncident:
    async def _create(by: str = "mira", **fields: object) -> dict[str, object]:
        body = {"title": "Database connection pool exhausted", **fields}
        res = await client.post("/api/v1/incidents", json=body, headers=people[by].headers)
        assert res.status_code == 201, res.text
        data: dict[str, object] = res.json()
        return data

    return _create

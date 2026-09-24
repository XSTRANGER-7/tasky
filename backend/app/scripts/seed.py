"""Seed demo data: ``python -m app.scripts.seed [--reset]`` (or ``make seed``).

* Demo users are always (re)set to their role, password and active state, so the demo
  logins work.
* 25 incidents spread over the last 14 days are created **through the real services**,
  so every audit event, SLA clock and comment is genuine; timestamps are then spread out
  so the dashboard trend, MTTR and timelines look like real operations.
* Incidents are only seeded into an empty table; ``--reset`` wipes incidents first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.base import utcnow
from app.db.session import dispose_engine, get_sessionmaker
from app.models import (
    Comment,
    EventType,
    InAppNotification,
    Incident,
    IncidentEvent,
    NotificationOutbox,
    Priority,
    Role,
    Status,
    Team,
    TeamMembership,
    TeamRole,
    User,
)
from app.repositories import user_repo
from app.schemas.incident import IncidentCreate
from app.services import comment_service, incident_service, watch_service
from app.services.auth_service import avatar_color_for

DEMO_PASSWORD = "demo1234"  # noqa: S105 - public demo credential, documented in the README

log = get_logger("app.seed")


@dataclass(frozen=True)
class DemoUser:
    key: str
    name: str
    email: str
    role: Role


DEMO_USERS = (
    DemoUser("ada", "Ada Admin", "admin@demo.io", Role.ADMIN),
    DemoUser("mira", "Mira Patel", "mira@demo.io", Role.MEMBER),
    DemoUser("sam", "Sam Viewer", "sam@demo.io", Role.VIEWER),
    DemoUser("jonas", "Jonas Weber", "jonas@demo.io", Role.MEMBER),
    DemoUser("priya", "Priya Nair", "priya@demo.io", Role.MEMBER),
)


@dataclass
class Spec:
    title: str
    priority: Priority
    category: str
    reporter: str
    age_h: float  # hours since creation
    assignee: str | None = None
    status: Status = Status.OPEN
    resolve_after_h: float | None = None  # for resolved/closed
    tags: list[str] = field(default_factory=list)
    description: str = ""
    comments: list[tuple[str, str, bool]] = field(default_factory=list)  # (who, body, internal)


P, S = Priority, Status
SPECS = [
    Spec(
        "Checkout API returning 502 for EU customers",
        P.CRITICAL,
        "payments",
        "mira",
        1.5,
        "jonas",
        S.IN_PROGRESS,
        tags=["prod", "checkout", "eu"],
        description="Since the **14:02** deploy roughly 30% of EU checkout requests fail with "
        "`502 Bad Gateway`.\n\n- Started after release `v2.14.0`\n- US region unaffected\n"
        "- Error rate graph: see the dashboard",
        comments=[
            (
                "jonas",
                "Rolling back `v2.14.0` on eu-west-1 now. @mira can you verify checkout?",
                False,
            ),
            ("jonas", "Suspect the new connection-pool limits in the gateway config.", True),
        ],
    ),
    Spec(
        "Database connection pool exhausted on orders-db",
        P.CRITICAL,
        "database",
        "priya",
        6,
        "mira",
        S.RESOLVED,
        resolve_after_h=3.2,
        tags=["prod", "postgres"],
        description="`FATAL: remaining connection slots are reserved` in orders-service logs.",
        comments=[
            ("mira", "Raised `max_connections` and added PgBouncer in transaction mode.", False),
            ("priya", "Confirmed: error rate back to baseline.", False),
        ],
    ),
    Spec(
        "Login page slow for users behind corporate proxies",
        P.HIGH,
        "auth",
        "mira",
        20,
        "priya",
        S.IN_PROGRESS,
        tags=["prod", "latency"],
        description="p95 login latency went from 400 ms to 4.2 s for some enterprise tenants.",
        comments=[
            ("priya", "Reproduced with a squid proxy. The OCSP stapling check times out.", False)
        ],
    ),
    Spec(
        "Password reset emails not delivered to Outlook",
        P.HIGH,
        "messaging",
        "ada",
        30,
        "jonas",
        S.OPEN,
        tags=["email"],
        description="Microsoft 365 marks our reset emails as spam since the DKIM key rotation.",
    ),
    Spec(
        "TLS certificate for api.example.com expires in 5 days",
        P.HIGH,
        "infrastructure",
        "jonas",
        40,
        "jonas",
        S.RESOLVED,
        resolve_after_h=2,
        tags=["tls"],
        comments=[("jonas", "Renewed and switched the cert-manager issuer to ACME.", False)],
    ),
    Spec(
        "Dashboard charts show UTC instead of local time",
        P.LOW,
        "frontend",
        "priya",
        52,
        None,
        S.OPEN,
        tags=["ui"],
    ),
    Spec(
        "VPN drops every 60 minutes on macOS clients",
        P.MEDIUM,
        "network",
        "mira",
        70,
        "priya",
        S.IN_PROGRESS,
        tags=["vpn", "macos"],
        comments=[("priya", "Matches the rekey interval. Testing a longer lifetime.", False)],
    ),
    Spec(
        "Nightly backup job exceeded its window",
        P.MEDIUM,
        "database",
        "ada",
        80,
        "mira",
        S.CLOSED,
        resolve_after_h=9,
        tags=["backup"],
        comments=[("mira", "Moved to incremental backups; runtime 2h -> 20m.", False)],
    ),
    Spec(
        "Search returns stale results after product update",
        P.MEDIUM,
        "search",
        "jonas",
        95,
        "mira",
        S.RESOLVED,
        resolve_after_h=14,
        tags=["search", "cache"],
    ),
    Spec("Printer on floor 3 keeps jamming", P.LOW, "facilities", "priya", 100, None, S.OPEN),
    Spec(
        "Mobile app crashes on Android 15 when opening invoices",
        P.HIGH,
        "mobile",
        "mira",
        120,
        "jonas",
        S.RESOLVED,
        resolve_after_h=6.5,
        tags=["android", "crash"],
        comments=[("jonas", "Null `pdfRenderer` on API 35 -- fix shipped in 3.8.2.", False)],
    ),
    Spec(
        "Webhook deliveries to partners delayed by 20 minutes",
        P.HIGH,
        "integrations",
        "ada",
        140,
        "priya",
        S.CLOSED,
        resolve_after_h=4,
        tags=["webhooks"],
    ),
    Spec(
        "Disk usage at 91% on logging cluster",
        P.MEDIUM,
        "infrastructure",
        "jonas",
        150,
        "jonas",
        S.RESOLVED,
        resolve_after_h=5,
        tags=["disk"],
    ),
    Spec(
        "SSO login loop for Okta users",
        P.CRITICAL,
        "auth",
        "priya",
        170,
        "mira",
        S.CLOSED,
        resolve_after_h=2.5,
        tags=["sso", "okta"],
        comments=[("mira", "SameSite change on the session cookie broke the IdP redirect.", True)],
    ),
    Spec(
        "CSV export truncates rows over 10k",
        P.MEDIUM,
        "reporting",
        "mira",
        190,
        "priya",
        S.RESOLVED,
        resolve_after_h=20,
    ),
    Spec(
        "Rate limiter blocks internal health checks",
        P.LOW,
        "infrastructure",
        "ada",
        210,
        "jonas",
        S.CLOSED,
        resolve_after_h=11,
    ),
    Spec(
        "Invoice PDFs render with the wrong currency symbol",
        P.MEDIUM,
        "payments",
        "priya",
        230,
        "mira",
        S.RESOLVED,
        resolve_after_h=26,
        tags=["i18n"],
    ),
    Spec(
        "Slack notifications duplicated for every comment",
        P.LOW,
        "integrations",
        "jonas",
        250,
        "priya",
        S.CLOSED,
        resolve_after_h=8,
    ),
    Spec(
        "Kubernetes node pool autoscaling too slowly",
        P.HIGH,
        "infrastructure",
        "ada",
        270,
        "jonas",
        S.RESOLVED,
        resolve_after_h=7,
        tags=["k8s"],
    ),
    Spec(
        "Customer avatars fail to upload over 2 MB",
        P.LOW,
        "frontend",
        "mira",
        290,
        None,
        S.OPEN,
        tags=["uploads"],
    ),
    Spec(
        "Scheduled reports sent twice on the 1st of the month",
        P.MEDIUM,
        "reporting",
        "priya",
        300,
        "mira",
        S.CLOSED,
        resolve_after_h=30,
    ),
    Spec(
        "Grafana alert for queue depth is flapping",
        P.LOW,
        "monitoring",
        "jonas",
        310,
        "jonas",
        S.RESOLVED,
        resolve_after_h=3,
    ),
    Spec(
        "Two-factor codes rejected after daylight saving change",
        P.HIGH,
        "auth",
        "ada",
        320,
        "priya",
        S.CLOSED,
        resolve_after_h=5,
        tags=["2fa"],
    ),
    Spec(
        "Checkout button hidden on small screens",
        P.MEDIUM,
        "frontend",
        "priya",
        326,
        "mira",
        S.RESOLVED,
        resolve_after_h=12,
        tags=["mobile", "ui"],
    ),
    Spec(
        "Legacy FTP endpoint still receiving traffic",
        P.LOW,
        "infrastructure",
        "mira",
        330,
        None,
        S.OPEN,
        tags=["cleanup"],
    ),
]


async def _users(session: AsyncSession) -> dict[str, User]:
    users: dict[str, User] = {}
    for demo in DEMO_USERS:
        user = await user_repo.get_user_by_email(session, demo.email)
        action = "reset"
        if user is None:
            user = User(email=demo.email, avatar_color=avatar_color_for(demo.email))
            session.add(user)
            action = "created"
        user.name, user.is_active = demo.name, True
        user.onboarded_at = user.onboarded_at or utcnow()  # skip the first-sign-in page
        user.password_hash = hash_password(DEMO_PASSWORD)
        users[demo.key] = user
        log.info("demo_user", email=demo.email, role=demo.role.value, action=action)
    await session.commit()
    return users


DEMO_TEAM_SLUG = "demo-ops"
DEMO_TEAM_ROLES = {
    Role.ADMIN: TeamRole.ADMIN,
    Role.MEMBER: TeamRole.MEMBER,
    Role.VIEWER: TeamRole.VIEWER,
}


async def _team(session: AsyncSession, users: dict[str, User]) -> Team:
    """The demo team every demo account belongs to, with the matching team roles. The
    users then act inside it, exactly as a request with ``X-Team-Id`` would."""
    team = await session.scalar(select(Team).where(Team.slug == DEMO_TEAM_SLUG))
    if team is None:
        team = Team(
            name="Demo Ops",
            slug=DEMO_TEAM_SLUG,
            description="Sample team for the demo data.",
            created_by_id=users["ada"].id,
        )
        session.add(team)
        await session.flush()
    for demo in DEMO_USERS:
        user = users[demo.key]
        role = DEMO_TEAM_ROLES[demo.role]
        membership = await session.get(TeamMembership, (team.id, user.id))
        if membership is None:
            session.add(TeamMembership(team_id=team.id, user_id=user.id, role=role))
        else:
            membership.role = role
        user.active_team_id, user.active_team_role = team.id, role
    await session.commit()
    log.info("demo_team", slug=DEMO_TEAM_SLUG)
    return team


async def _play(
    session: AsyncSession, settings: Settings, users: dict[str, User], spec: Spec
) -> uuid.UUID:
    """Drive one incident through the real service layer."""
    admin = users["ada"]
    incident, _ = await incident_service.create(
        session,
        settings,
        users[spec.reporter],
        IncidentCreate(
            title=spec.title,
            description=spec.description,
            priority=spec.priority,
            category=spec.category,
            tags=spec.tags,
        ),
    )
    key = incident.key
    # The admin follows the urgent work, so watchers and their notifications are real too.
    if spec.priority in (Priority.CRITICAL, Priority.HIGH) and spec.reporter != "ada":
        await watch_service.watch(session, admin, key)
    if spec.assignee:
        await incident_service.assign(session, settings, admin, key, users[spec.assignee].id)
    if spec.status == Status.IN_PROGRESS:
        await incident_service.transition(
            session, settings, users[spec.assignee or "ada"], key, Status.IN_PROGRESS
        )
    for who, body, internal in spec.comments:
        await comment_service.add(
            session, settings, users[who], key, body=body, is_internal=internal
        )
    if spec.status in (Status.RESOLVED, Status.CLOSED):
        if spec.assignee:
            await incident_service.transition(
                session, settings, users[spec.assignee], key, Status.IN_PROGRESS
            )
        await incident_service.transition(
            session,
            settings,
            users[spec.assignee or "ada"],
            key,
            Status.RESOLVED,
            note="Root cause fixed and verified.",
        )
    if spec.status == Status.CLOSED:
        await incident_service.transition(session, settings, admin, key, Status.CLOSED)
    return incident.id


async def _spread_in_time(
    session: AsyncSession, settings: Settings, incident_id: uuid.UUID, spec: Spec, now: datetime
) -> None:
    """Rewrite timestamps so the history looks real: created ``age_h`` ago, events spaced
    across the working period, resolution after ``resolve_after_h``."""
    created = now - timedelta(hours=spec.age_h)
    end = (
        created + timedelta(hours=spec.resolve_after_h)
        if spec.resolve_after_h
        else now - timedelta(hours=spec.age_h * 0.2)
    )
    events = (
        await session.scalars(
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.seq)
        )
    ).all()
    last_status_change = [e for e in events if e.event_type == EventType.STATUS_CHANGED]
    step = (end - created) / max(len(events) - 1, 1)
    times: dict[uuid.UUID, datetime] = {}
    for i, event in enumerate(events):
        at = created + step * i
        if spec.status == Status.CLOSED and last_status_change and event is last_status_change[-1]:
            at = end + timedelta(hours=2)  # closed a little after resolution
        event.created_at = at
        times[event.id] = at
        if event.event_type == EventType.COMMENTED and isinstance(event.new_value, dict):
            await session.execute(
                update(Comment)
                .where(Comment.id == uuid.UUID(event.new_value["comment_id"]))
                .values(created_at=at)
            )

    def first(pred: object) -> datetime | None:
        for e in events:
            if pred(e):  # type: ignore[operator]
                return times[e.id]
        return None

    incident = await session.get(Incident, incident_id)
    assert incident is not None  # noqa: S101
    response_due, resolution_due = incident_service.compute_due(created, spec.priority, settings)
    incident.created_at = created
    incident.response_due_at = response_due
    incident.resolution_due_at = resolution_due
    incident.first_response_at = first(
        lambda e: (
            e.event_type == EventType.ASSIGNED
            or (e.event_type == EventType.COMMENTED and e.actor_id != incident.reporter_id)
        )
    )
    incident.resolved_at = first(
        lambda e: e.event_type == EventType.STATUS_CHANGED and e.new_value == "resolved"
    )
    incident.closed_at = first(
        lambda e: e.event_type == EventType.STATUS_CHANGED and e.new_value == "closed"
    )
    incident.updated_at = times[events[-1].id] if events else created

    # Notifications follow their events in time. Seeded history never emails anyone
    # (spec: "no test emails"), so its outbox rows are discarded; in-app items stay, and
    # anything older than a day counts as already read.
    await session.execute(
        delete(NotificationOutbox).where(NotificationOutbox.incident_id == incident_id)
    )
    for event_id, at in times.items():
        await session.execute(
            update(InAppNotification)
            .where(InAppNotification.event_id == event_id)
            .values(created_at=at, read_at=at if now - at > timedelta(days=1) else None)
        )
    await session.commit()


async def seed(*, reset: bool) -> None:
    settings = get_settings()
    async with get_sessionmaker()() as session:
        users = await _users(session)
        await _team(session, users)
        if reset:
            await session.execute(
                text(
                    "TRUNCATE incidents, comments, incident_events, idempotency_keys, "
                    "notification_outbox, in_app_notifications, incident_watchers, attachments, "
                    "ai_suggestions "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await session.commit()
            log.info("incidents_reset")
        existing = int(await session.scalar(select(func.count()).select_from(Incident)) or 0)
        if existing:
            log.info("incidents_skipped", existing=existing, hint="use --reset to recreate them")
        else:
            now = utcnow()
            for spec in sorted(SPECS, key=lambda s: -s.age_h):  # oldest first -> INC numbers ascend
                incident_id = await _play(session, settings, users, spec)
                await _spread_in_time(session, settings, incident_id, spec, now)
            log.info("incidents_seeded", count=len(SPECS))
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Tasky demo data")
    parser.add_argument("--reset", action="store_true", help="delete all incidents first")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="seed even when APP_ENV=production (a public demo; never real data)",
    )
    args = parser.parse_args()
    settings = get_settings()
    if settings.is_production and not args.allow_production:
        sys.exit(
            "Refusing to seed demo data into a production database: it creates accounts with "
            "a public password. For real use, people sign up and create their teams. "
            "For a public demo, pass --allow-production (and set DEMO_MODE=true)."
        )
    configure_logging(settings)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(seed(reset=args.reset), loop_factory=loop_factory)


if __name__ == "__main__":
    main()

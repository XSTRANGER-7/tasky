"""Enqueue notifications inside the caller's transaction (transactional outbox, spec 9).

``notify`` never commits. The outbox rows, in-app rows and the change that caused them
commit together or not at all -- so no email is ever sent about a rolled-back change and
none is lost if the process dies after the commit. The worker delivers email later.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    InAppNotification,
    Incident,
    IncidentAssignee,
    IncidentEvent,
    IncidentWatcher,
    NotificationKind,
    NotificationOutbox,
    User,
)
from app.models.incident import key_for
from app.notifications import recipients
from app.notifications.rendering import RenderedEmail, render_email
from app.realtime import publish as realtime
from app.repositories import team_repo

log = get_logger(__name__)


async def watchers_of(session: AsyncSession, incident_id: uuid.UUID) -> Sequence[User]:
    stmt = (
        select(User)
        .join(IncidentWatcher, IncidentWatcher.user_id == User.id)
        .where(IncidentWatcher.incident_id == incident_id)
    )
    return (await session.scalars(stmt)).all()


async def assignees_of(session: AsyncSession, incident_id: uuid.UUID) -> list[User]:
    """Everyone assigned to the incident, lead first (read fresh: it may have just changed)."""
    stmt = (
        select(User)
        .join(IncidentAssignee, IncidentAssignee.user_id == User.id)
        .where(IncidentAssignee.incident_id == incident_id)
        .order_by(IncidentAssignee.position)
    )
    return list((await session.scalars(stmt)).all())


async def _team_members(session: AsyncSession, team_id: uuid.UUID) -> list[User]:
    return [user for user, _ in await team_repo.members(session, team_id)]


# Team admins hear about these for every incident in their team.
ADMINS_HEAR = frozenset(
    {
        NotificationKind.INCIDENT_ASSIGNED,
        NotificationKind.INCIDENT_UPDATED,
        NotificationKind.INCIDENT_RESOLVED,
        NotificationKind.SLA_BREACHED,
    }
)


async def notify(
    session: AsyncSession,
    settings: Settings,
    kind: NotificationKind,
    incident: Incident,
    event: IncidentEvent,
    *,
    actor: User | None,
    body: str | None = None,
    internal: bool = False,
    added: Sequence[User] = (),
    assigned: Sequence[User] = (),
) -> int:
    """Plan and stage deliveries for one event. Returns how many people were notified.

    Only people in the incident's team hear about it: @mentions resolve against team
    members, an SLA breach also goes to the team's admins, and someone who has left the
    team stops getting its mail."""
    team_id = incident.team_id
    watchers = await watchers_of(session, incident.id)
    everyone_assigned = await assignees_of(session, incident.id)
    lead = everyone_assigned[0] if everyone_assigned else None
    co_assignees = everyone_assigned[1:]
    mentioned: Sequence[User] = []
    admins: Sequence[User] = []
    if kind == NotificationKind.INCIDENT_COMMENTED and body:
        mentioned = recipients.resolve_mentions(body, await _team_members(session, team_id))
    if kind in ADMINS_HEAR:
        admins = await team_repo.managers(session, team_id)

    # Everyone who might be notified carries their role in this team, so the internal-note
    # rule ("never to viewers") uses the team role rather than the platform role.
    candidates = [
        incident.reporter,
        *everyone_assigned,
        *watchers,
        *mentioned,
        *admins,
        *added,
        *assigned,
    ]
    roles = await team_repo.roles_in_team(
        session, team_id, [p.id for p in candidates if p is not None]
    )
    for person in candidates:
        if person is not None:
            person.active_team_id = team_id
            person.active_team_role = roles.get(person.id)
    allowed = set(roles)

    deliveries = recipients.plan(
        kind,
        actor_id=actor.id if actor else None,
        reporter=incident.reporter,
        assignee=lead,
        co_assignees=co_assignees,
        watchers=watchers,
        mentioned=mentioned,
        admins=admins,
        added=added or assigned,
        internal=internal,
    )
    deliveries = [d for d in deliveries if d.user.id in allowed]

    now = utcnow()
    for d in deliveries:
        user = d.user
        assert isinstance(user, User)  # noqa: S101 - plan() returns what it was given
        email = render_email(
            d.kind,
            incident,
            actor=actor,
            recipient=user,
            base_url=settings.app_base_url,
            when=now,
            body=body,
            assigned=assigned,
        )
        if d.email:
            session.add(
                NotificationOutbox(
                    event_id=event.id,
                    incident_id=incident.id,
                    team_id=team_id,
                    recipient_user_id=user.id,
                    recipient_email=user.email,  # snapshot: records where it went
                    kind=d.kind,
                    subject=email.subject,
                    body_text=email.text,
                    body_html=email.html,
                    next_attempt_at=now,
                )
            )
        session.add(
            InAppNotification(
                user_id=user.id,
                incident_id=incident.id,
                event_id=event.id,
                team_id=team_id,
                actor_id=actor.id if actor else None,
                kind=d.kind,
                title=email.subject,
                body=email.summary,
            )
        )
        realtime.queue(
            session,
            {
                "type": "notification.new",
                "user": str(user.id),
                "incident": key_for(incident.number),
            },
        )

    if deliveries:
        log.info(
            "notifications_enqueued",
            kind=kind.value,
            incident=key_for(incident.number),
            recipients=len(deliveries),
            emails=sum(1 for d in deliveries if d.email),
        )
    return len(deliveries)


# ---------------------------------------------------------------- non-incident messages

# Sent even to people who turned incident emails off: they asked for it, or it gates access.
ALWAYS_EMAIL = frozenset({NotificationKind.PASSWORD_RESET})


def notify_user(
    session: AsyncSession,
    user: User,
    kind: NotificationKind,
    email: RenderedEmail,
    *,
    actor: User | None = None,
    team_id: uuid.UUID | None = None,
    link: str | None = None,
    in_app: bool = True,
) -> None:
    """Stage one email (outbox) and one in-app notification for a single person, in the
    caller's transaction -- the same guarantees as :func:`notify`, for mail that is not
    about an incident (team requests, password resets)."""
    if not user.is_active:
        return
    now = utcnow()
    if user.notify_email or kind in ALWAYS_EMAIL:
        session.add(
            NotificationOutbox(
                recipient_user_id=user.id,
                team_id=team_id,
                recipient_email=user.email,
                kind=kind,
                subject=email.subject,
                body_text=email.text,
                body_html=email.html,
                next_attempt_at=now,
            )
        )
    if in_app:
        session.add(
            InAppNotification(
                user_id=user.id,
                team_id=team_id,
                link=link,
                actor_id=actor.id if actor else None,
                kind=kind,
                title=email.subject,
                body=email.summary,
            )
        )
        realtime.queue(session, {"type": "notification.new", "user": str(user.id)})
    log.info("notification_enqueued", kind=kind.value, recipient=str(user.id))

"""Team use cases: create, discover, request to join, approve/reject, manage members.

Rules
* There is no platform-wide admin. Anyone signed in may create a team, and its creator
  becomes that team's admin.
* Anyone may ask to join a team. Its admins get an email and an in-app request;
  approving adds the person with the role the admin picks (member by default), and the
  requester is told either way.
* A team's admins manage its members (including making co-admins), requests and
  settings, and may delete it. A team can never be left without an admin.

Each public function is one transaction and commits it.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, InvalidInput, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import (
    Attachment,
    Incident,
    IncidentWatcher,
    JoinRequestStatus,
    NotificationKind,
    Team,
    TeamJoinRequest,
    TeamMembership,
    TeamRole,
    User,
)
from app.notifications.rendering import render_message
from app.repositories import team_repo, user_repo
from app.services import dashboard_service
from app.services.notification_service import notify_user

log = get_logger(__name__)

SLUG_CHARS = re.compile(r"[^a-z0-9]+")
TEAM_FOOTER = "You get this because of your role in this team on Tasky."


@dataclass(frozen=True)
class TeamView:
    team: Team
    member_count: int
    my_role: TeamRole | None
    pending_request_id: uuid.UUID | None


# ---------------------------------------------------------------- helpers


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = SLUG_CHARS.sub("-", ascii_name.lower()).strip("-")
    return slug[:60] or "team"


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while await team_repo.slug_taken(session, slug):
        slug, n = f"{base}-{n}", n + 1
    return slug


async def _team_or_404(session: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await team_repo.get_team(session, team_id)
    if team is None:
        raise NotFound("Team not found", code="team_not_found")
    return team


async def _role_of(session: AsyncSession, team_id: uuid.UUID, user: User) -> TeamRole | None:
    membership = await team_repo.get_membership(session, team_id, user.id)
    return membership.role if membership else None


async def _require_admin(session: AsyncSession, team_id: uuid.UUID, actor: User) -> None:
    role = await _role_of(session, team_id, actor)
    if role is None or not role.manages_team:
        raise PermissionDenied("Only this team's admins can do this", code="not_team_admin")


async def _require_member(session: AsyncSession, team_id: uuid.UUID, actor: User) -> None:
    if await _role_of(session, team_id, actor) is None:
        raise PermissionDenied("You are not a member of this team", code="not_team_member")


async def _keep_an_admin(session: AsyncSession, team_id: uuid.UUID, message: str) -> None:
    if await team_repo.count_admins(session, team_id) <= 1:
        raise Conflict(message, code="last_admin")


def _url(settings: Settings, path: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}{path}"


# ---------------------------------------------------------------- reads


async def my_teams(session: AsyncSession, actor: User) -> list[TeamView]:
    rows = await team_repo.teams_of_user(session, actor.id)
    counts = await team_repo.member_counts(session, [t.id for t, _ in rows])
    return [TeamView(t, counts.get(t.id, 0), role, None) for t, role in rows]


async def discover(session: AsyncSession, actor: User, q: str | None) -> list[TeamView]:
    """Every team matching ``q``, with the caller's membership or open request."""
    teams = await team_repo.search_teams(session, q)
    ids = [t.id for t in teams]
    counts = await team_repo.member_counts(session, ids)
    my_roles = {t.id: role for t, role in await team_repo.teams_of_user(session, actor.id)}
    pending = {
        r.team_id: r.id
        for r in await team_repo.list_requests(
            session, user_id=actor.id, status=JoinRequestStatus.PENDING
        )
    }
    return [TeamView(t, counts.get(t.id, 0), my_roles.get(t.id), pending.get(t.id)) for t in teams]


async def get_team(session: AsyncSession, actor: User, team_id: uuid.UUID) -> TeamView:
    team = await _team_or_404(session, team_id)
    await _require_member(session, team_id, actor)
    counts = await team_repo.member_counts(session, [team_id])
    return TeamView(team, counts.get(team_id, 0), await _role_of(session, team_id, actor), None)


async def members(
    session: AsyncSession, actor: User, team_id: uuid.UUID
) -> Sequence[tuple[User, TeamMembership]]:
    await _team_or_404(session, team_id)
    await _require_member(session, team_id, actor)
    return await team_repo.members(session, team_id, include_inactive=True)


async def my_requests(session: AsyncSession, actor: User) -> Sequence[TeamJoinRequest]:
    return await team_repo.list_requests(session, user_id=actor.id, limit=50)


async def requests_for_team(
    session: AsyncSession,
    actor: User,
    team_id: uuid.UUID,
    status: JoinRequestStatus | None,
) -> Sequence[TeamJoinRequest]:
    await _team_or_404(session, team_id)
    await _require_admin(session, team_id, actor)
    return await team_repo.list_requests(session, team_ids=[team_id], status=status)


async def requests_to_review(session: AsyncSession, actor: User) -> Sequence[TeamJoinRequest]:
    """Pending requests for every team the caller is an admin of."""
    managed = [
        t.id for t, role in await team_repo.teams_of_user(session, actor.id) if role.manages_team
    ]
    if not managed:
        return []
    return await team_repo.list_requests(
        session, team_ids=managed, status=JoinRequestStatus.PENDING
    )


# ---------------------------------------------------------------- create / edit / delete


async def create_team(
    session: AsyncSession, actor: User, *, name: str, description: str = ""
) -> Team:
    team = Team(
        name=name,
        slug=await _unique_slug(session, name),
        description=description,
        created_by_id=actor.id,
    )
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=actor.id, role=TeamRole.ADMIN))
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a slug race with a concurrent create
        await session.rollback()
        raise Conflict("A team with this name was just created; try again") from exc
    log.info("team_created", team_id=str(team.id), by=str(actor.id))
    return team


async def update_team(
    session: AsyncSession,
    actor: User,
    team_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
) -> Team:
    team = await _team_or_404(session, team_id)
    await _require_admin(session, team_id, actor)
    if name is not None:
        team.name = name
    if description is not None:
        team.description = description
    await session.commit()
    return team


async def delete_team(session: AsyncSession, actor: User, team_id: uuid.UUID) -> list[str]:
    """Delete a team and everything in it (its admins only). Returns the storage keys of
    its attachments, for the caller to remove after the commit."""
    team = await _team_or_404(session, team_id)
    await _require_admin(session, team_id, actor)
    keys = list(
        (
            await session.scalars(
                select(Attachment.storage_key)
                .join(Incident, Incident.id == Attachment.incident_id)
                .where(Incident.team_id == team_id)
            )
        ).all()
    )
    await session.delete(team)  # incidents, comments, events, requests... cascade
    await session.commit()
    dashboard_service.invalidate(team_id)
    log.info("team_deleted", team_id=str(team_id), by=str(actor.id), attachments=len(keys))
    return keys


# ---------------------------------------------------------------- join requests


async def request_to_join(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    team_id: uuid.UUID,
    *,
    message: str = "",
) -> TeamJoinRequest:
    team = await _team_or_404(session, team_id)
    if await _role_of(session, team_id, actor) is not None:
        raise Conflict("You are already a member of this team", code="already_member")
    existing = await team_repo.pending_request(session, team_id, actor.id)
    if existing is not None:
        return existing  # idempotent: asking twice is one request

    request = TeamJoinRequest(team_id=team_id, user_id=actor.id, message=message)
    session.add(request)
    await session.flush()

    reviewers = list(await team_repo.managers(session, team_id))
    now = utcnow()
    for reviewer in reviewers:
        email = render_message(
            subject=f"{actor.name} asked to join {team.name}",
            headline="New join request",
            title=f"{actor.name} wants to join {team.name}",
            intro=f"{actor.name} ({actor.email}) asked to join {team.name}. Approve to give "
            "them access to the team's tasks, or reject the request.",
            quote=message or None,
            cta="Review the request",
            url=_url(settings, f"/team/requests?team={team_id}"),
            recipient=reviewer,
            when=now,
            footer=TEAM_FOOTER,
        )
        notify_user(
            session,
            reviewer,
            NotificationKind.TEAM_JOIN_REQUESTED,
            email,
            actor=actor,
            team_id=team_id,
            link=f"/team/requests?team={team_id}",
        )
    try:
        await session.commit()
    except IntegrityError:  # a concurrent identical request won the race
        await session.rollback()
        existing = await team_repo.pending_request(session, team_id, actor.id)
        if existing is None:
            raise
        return existing
    log.info(
        "team_join_requested",
        team_id=str(team_id),
        user_id=str(actor.id),
        reviewers=len(reviewers),
    )
    return request


async def cancel_request(
    session: AsyncSession, actor: User, request_id: uuid.UUID
) -> TeamJoinRequest:
    request = await team_repo.get_request(session, request_id, for_update=True)
    if request is None or request.user_id != actor.id:
        raise NotFound("Request not found")
    if request.status != JoinRequestStatus.PENDING:
        raise Conflict("This request was already decided", code="request_decided")
    request.status = JoinRequestStatus.CANCELLED
    request.decided_at = utcnow()
    await session.commit()
    return request


async def decide(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    request_id: uuid.UUID,
    *,
    approve: bool,
    role: TeamRole = TeamRole.MEMBER,
) -> TeamJoinRequest:
    request = await team_repo.get_request(session, request_id, for_update=True)
    if request is None:
        raise NotFound("Request not found")
    await _require_admin(session, request.team_id, actor)
    if request.status != JoinRequestStatus.PENDING:
        raise Conflict("This request was already decided", code="request_decided")

    now = utcnow()
    team, requester = request.team, request.user
    request.decided_by_id = actor.id
    request.decided_at = now
    if approve:
        if await team_repo.get_membership(session, team.id, requester.id) is None:
            session.add(TeamMembership(team_id=team.id, user_id=requester.id, role=role))
        request.status = JoinRequestStatus.APPROVED
        request.granted_role = role
        email = render_message(
            subject=f"You're in: welcome to {team.name}",
            headline="Request approved",
            title=f"Welcome to {team.name}",
            intro=f"{actor.name} approved your request. You joined {team.name} as "
            f"{'an' if role == TeamRole.ADMIN else 'a'} {role.value}, "
            "and can now see and work on the team's tasks.",
            cta=f"Open {team.name}",
            url=_url(settings, f"/?team={team.id}"),
            recipient=requester,
            when=now,
            footer=TEAM_FOOTER,
        )
        kind = NotificationKind.TEAM_JOIN_APPROVED
        link = f"/?team={team.id}"
    else:
        request.status = JoinRequestStatus.REJECTED
        email = render_message(
            subject=f"Your request to join {team.name} was declined",
            headline="Request declined",
            title=f"Not this time: {team.name}",
            intro=f"{actor.name} declined your request to join {team.name}. You can ask "
            "again later, or create your own team.",
            cta="Find another team",
            url=_url(settings, "/?find=team"),
            recipient=requester,
            when=now,
            footer=TEAM_FOOTER,
        )
        kind = NotificationKind.TEAM_JOIN_REJECTED
        link = "/?find=team"
    notify_user(session, requester, kind, email, actor=actor, team_id=team.id, link=link)
    await session.commit()
    log.info(
        "team_join_decided",
        request_id=str(request.id),
        approved=approve,
        role=role.value if approve else None,
        by=str(actor.id),
    )
    return request


# ---------------------------------------------------------------- members


def _article(role: TeamRole) -> str:
    return "an" if role == TeamRole.ADMIN else "a"


def _tell_member(
    session: AsyncSession,
    settings: Settings,
    person: User,
    kind: NotificationKind,
    *,
    actor: User,
    team: Team,
    subject: str,
    headline: str,
    intro: str,
    cta: str,
    path: str,
) -> None:
    """Email + in-app note to someone whose membership an admin just changed."""
    if person.id == actor.id:
        return  # your own action needs no email
    email = render_message(
        subject=subject,
        headline=headline,
        title=team.name,
        intro=intro,
        cta=cta,
        url=_url(settings, path),
        recipient=person,
        when=utcnow(),
        footer=TEAM_FOOTER,
    )
    notify_user(session, person, kind, email, actor=actor, team_id=team.id, link=path)


async def add_member(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    team_id: uuid.UUID,
    *,
    email: str,
    role: TeamRole,
) -> tuple[User, TeamMembership]:
    """An admin adds an existing account straight into the team; that person is emailed."""
    team = await _team_or_404(session, team_id)
    await _require_admin(session, team_id, actor)
    user = await user_repo.get_user_by_email(session, email)
    if user is None or not user.is_active:
        raise InvalidInput(
            "No active account with this email: they need to sign up first",
            code="unknown_user",
            details={"fields": [{"loc": ["body", "email"], "message": "No such account"}]},
        )
    if await team_repo.get_membership(session, team_id, user.id) is not None:
        raise Conflict("Already a member of this team", code="already_member")
    membership = TeamMembership(team_id=team_id, user_id=user.id, role=role)
    session.add(membership)
    # Adding someone answers their open request, if they had one.
    pending = await team_repo.pending_request(session, team_id, user.id)
    if pending is not None:
        pending.status = JoinRequestStatus.APPROVED
        pending.granted_role = role
        pending.decided_by_id = actor.id
        pending.decided_at = utcnow()
    _tell_member(
        session,
        settings,
        user,
        NotificationKind.TEAM_MEMBER_ADDED,
        actor=actor,
        team=team,
        subject=f"{actor.name} added you to {team.name}",
        headline="Added to a team",
        intro=f"{actor.name} added you to {team.name} as {_article(role)} {role.value}. "
        "You can now see and work on the team's tasks.",
        cta=f"Open {team.name}",
        path=f"/?team={team.id}",
    )
    await session.commit()
    log.info("team_member_added", team_id=str(team_id), user_id=str(user.id), by=str(actor.id))
    return user, membership


async def change_role(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    role: TeamRole,
) -> TeamMembership:
    team = await _team_or_404(session, team_id)
    await _require_admin(session, team_id, actor)
    membership = await team_repo.get_membership(session, team_id, user_id, for_update=True)
    if membership is None:
        raise NotFound("Not a member of this team")
    if membership.role == role:
        return membership
    if membership.role == TeamRole.ADMIN:
        await _keep_an_admin(
            session, team_id, "A team needs at least one admin: make someone else an admin first"
        )
    membership.role = role
    person = await user_repo.get_user(session, user_id)
    if person is not None:
        _tell_member(
            session,
            settings,
            person,
            NotificationKind.TEAM_ROLE_CHANGED,
            actor=actor,
            team=team,
            subject=f"You are now {_article(role)} {role.value} of {team.name}",
            headline="Team role changed",
            intro=f"{actor.name} made you {_article(role)} {role.value} of {team.name}.",
            cta=f"Open {team.name}",
            path=f"/team?team={team.id}",
        )
    await session.commit()
    log.info(
        "team_role_changed",
        team_id=str(team_id),
        user_id=str(user_id),
        role=role.value,
        by=str(actor.id),
    )
    return membership


async def remove_member(
    session: AsyncSession,
    settings: Settings,
    actor: User,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Admins remove members (who are emailed); anyone may remove themself (leave). The
    last admin can neither leave nor be removed. Leaving also stops watching the team's
    incidents."""
    team = await _team_or_404(session, team_id)
    if user_id != actor.id:
        await _require_admin(session, team_id, actor)
    membership = await team_repo.get_membership(session, team_id, user_id, for_update=True)
    if membership is None:
        raise NotFound("Not a member of this team")
    if membership.role == TeamRole.ADMIN:
        await _keep_an_admin(
            session,
            team_id,
            "A team needs at least one admin: make someone else an admin first, or delete the team",
        )
    await session.delete(membership)
    await session.execute(
        delete(IncidentWatcher).where(
            IncidentWatcher.user_id == user_id,
            IncidentWatcher.incident_id.in_(select(Incident.id).where(Incident.team_id == team_id)),
        )
    )
    person = await user_repo.get_user(session, user_id)
    if person is not None:
        # No link into a team they can no longer open: point at the team finder instead.
        _tell_member(
            session,
            settings,
            person,
            NotificationKind.TEAM_MEMBER_REMOVED,
            actor=actor,
            team=team,
            subject=f"You were removed from {team.name}",
            headline="Removed from a team",
            intro=f"{actor.name} removed you from {team.name}, so you no longer have access "
            "to its tasks. You can ask to join again, or join another team.",
            cta="Find a team",
            path="/?find=team",
        )
    await session.commit()
    log.info("team_member_removed", team_id=str(team_id), user_id=str(user_id), by=str(actor.id))

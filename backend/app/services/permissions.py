"""Who may do what to an incident (spec section 7, permission matrix).

Pure functions over plain objects: no database, no HTTP. The service layer calls them
before every mutation, and they also produce the ``permissions`` / ``allowed_transitions``
hints the UI renders -- the UI hides what the server would refuse, but the server decides.

    Action                         Viewer   Member                 Admin
    View                           yes      yes                    yes
    Create incident                -        yes                    yes
    Edit title/description/...     -        reporter or assignee   yes
    Assign / reassign              -        yes                    yes
    open -> in_progress (start)    -        assignee               yes
    in_progress -> open (pause)    -        assignee               yes
    -> resolved                    -        assignee or reporter   yes
    resolved -> closed             -        -                      yes
    resolved -> open (reopen)      -        reporter or assignee   yes
    Comment                        -        yes                    yes
    See internal notes             -        yes                    yes
    Edit / delete comment          -        own, within 15 min     any
    Delete / restore incident      -        -                      yes

"Role" here is the person's role in the incident's team (see ``models/team.py``). There
is no platform-wide admin: a team's admins are admins in that team only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Protocol

from app.models import Role, Status

COMMENT_EDIT_WINDOW = timedelta(minutes=15)

# The single source of truth for the lifecycle.
ALLOWED: dict[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.IN_PROGRESS, Status.RESOLVED}),
    Status.IN_PROGRESS: frozenset({Status.OPEN, Status.RESOLVED}),
    Status.RESOLVED: frozenset({Status.CLOSED, Status.OPEN}),
    Status.CLOSED: frozenset(),  # terminal
}


class Actor(Protocol):
    @property
    def id(self) -> uuid.UUID: ...
    @property
    def role(self) -> Role: ...


class IncidentLike(Protocol):
    @property
    def status(self) -> Status: ...
    @property
    def reporter_id(self) -> uuid.UUID: ...
    @property
    def assignee_id(self) -> uuid.UUID | None: ...


class CommentLike(Protocol):
    @property
    def author_id(self) -> uuid.UUID: ...
    @property
    def created_at(self) -> datetime: ...


def role_of(actor: Actor) -> Role:
    """The role that governs incident actions: the team role in the active team when the
    actor carries one (a ``User`` on a team-scoped route), else the plain ``role``."""
    effective = getattr(actor, "effective_role", None)
    return effective if isinstance(effective, Role) else actor.role


def is_admin(actor: Actor) -> bool:
    return role_of(actor) == Role.ADMIN


def can_work(actor: Actor) -> bool:
    """Members and admins act; viewers only read."""
    return role_of(actor) in (Role.ADMIN, Role.MEMBER)


def _involved(actor: Actor, incident: IncidentLike) -> bool:
    # Every assignee counts, not only the lead (plain test doubles carry just assignee_id).
    assignees = getattr(incident, "assignee_ids", None) or {incident.assignee_id}
    return actor.id == incident.reporter_id or actor.id in assignees


def can_create(actor: Actor) -> bool:
    return can_work(actor)


def can_edit(actor: Actor, incident: IncidentLike) -> bool:
    if incident.status == Status.CLOSED:
        return False
    return is_admin(actor) or (can_work(actor) and _involved(actor, incident))


def can_assign(actor: Actor, incident: IncidentLike) -> bool:
    return can_work(actor) and incident.status != Status.CLOSED


def can_comment(actor: Actor) -> bool:
    return can_work(actor)


def can_see_internal(actor: Actor) -> bool:
    return can_work(actor)


def can_delete(actor: Actor, incident: IncidentLike | None = None) -> bool:
    """The team's admins, or the task's creator while they can still work in the team
    (a creator later made a viewer is read-only like any viewer)."""
    if is_admin(actor):
        return True
    return incident is not None and can_work(actor) and actor.id == incident.reporter_id


def can_restore(actor: Actor) -> bool:
    """Deleted tasks sit in the admins' recycle bin, so only admins bring them back."""
    return is_admin(actor)


def can_transition(actor: Actor, incident: IncidentLike, new: Status) -> bool:
    """Permission only; legality of the move itself is checked against ALLOWED."""
    if is_admin(actor):
        return True
    if not can_work(actor):
        return False
    is_assignee = actor.id == incident.assignee_id
    is_reporter = actor.id == incident.reporter_id
    current = incident.status
    if new == Status.CLOSED:
        return False  # admin only
    if new == Status.RESOLVED:
        return is_assignee or is_reporter
    if current == Status.RESOLVED and new == Status.OPEN:
        return is_assignee or is_reporter  # reopen
    return is_assignee  # start / pause


def allowed_transitions(actor: Actor, incident: IncidentLike) -> list[Status]:
    """The moves this actor can make right now -- exactly what the UI should offer."""
    moves = []
    for new in ALLOWED[incident.status]:
        if new == Status.IN_PROGRESS and incident.assignee_id is None:
            continue  # "start" needs an assignee (would be 422)
        if can_transition(actor, incident, new):
            moves.append(new)
    order = list(Status)
    return sorted(moves, key=order.index)


def can_modify_comment(actor: Actor, comment: CommentLike, now: datetime) -> bool:
    if is_admin(actor):
        return True
    return (
        can_work(actor)
        and comment.author_id == actor.id
        and now - comment.created_at <= COMMENT_EDIT_WINDOW
    )

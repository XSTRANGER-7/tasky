"""The permission matrix, state machine and SLA maths as pure functions (no DB, no HTTP)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.errors import NotFound
from app.models import Priority, Role, Status
from app.services import permissions as perms
from app.services.incident_service import compute_due, parse_ident
from app.services.presenters import sla_state

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@dataclass
class U:
    role: Role
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class I:  # noqa: E742 - short name reads well in a truth table
    status: Status
    reporter_id: uuid.UUID
    assignee_id: uuid.UUID | None = None


@dataclass
class C:
    author_id: uuid.UUID
    created_at: datetime


ADMIN, REPORTER, ASSIGNEE, OTHER, VIEWER = (
    U(Role.ADMIN),
    U(Role.MEMBER),
    U(Role.MEMBER),
    U(Role.MEMBER),
    U(Role.VIEWER),
)


def incident(status: Status, *, assigned: bool = True) -> I:
    return I(status, REPORTER.id, ASSIGNEE.id if assigned else None)


# ---------------------------------------------------------------- state machine


def test_allowed_map_matches_the_spec() -> None:
    assert {
        Status.OPEN: {Status.IN_PROGRESS, Status.RESOLVED},
        Status.IN_PROGRESS: {Status.OPEN, Status.RESOLVED},
        Status.RESOLVED: {Status.CLOSED, Status.OPEN},
        Status.CLOSED: set(),
    } == perms.ALLOWED


@pytest.mark.parametrize(
    ("actor", "status", "expected"),
    [
        (ASSIGNEE, Status.OPEN, [Status.IN_PROGRESS, Status.RESOLVED]),
        (REPORTER, Status.OPEN, [Status.RESOLVED]),
        (OTHER, Status.OPEN, []),
        (VIEWER, Status.OPEN, []),
        (ADMIN, Status.OPEN, [Status.IN_PROGRESS, Status.RESOLVED]),
        (ASSIGNEE, Status.IN_PROGRESS, [Status.OPEN, Status.RESOLVED]),
        (REPORTER, Status.IN_PROGRESS, [Status.RESOLVED]),
        (REPORTER, Status.RESOLVED, [Status.OPEN]),  # reopen, but not close
        (ASSIGNEE, Status.RESOLVED, [Status.OPEN]),
        (ADMIN, Status.RESOLVED, [Status.OPEN, Status.CLOSED]),
        (ADMIN, Status.CLOSED, []),  # terminal, even for admins
    ],
)
def test_allowed_transitions_per_actor(actor: U, status: Status, expected: list[Status]) -> None:
    assert perms.allowed_transitions(actor, incident(status)) == expected


def test_start_is_not_offered_without_an_assignee() -> None:
    assert perms.allowed_transitions(ADMIN, incident(Status.OPEN, assigned=False)) == [
        Status.RESOLVED
    ]


# ---------------------------------------------------------------- permission matrix


@pytest.mark.parametrize(
    ("actor", "can_edit", "can_assign", "can_create", "can_comment", "can_delete"),
    [
        (ADMIN, True, True, True, True, True),
        (REPORTER, True, True, True, True, True),  # the creator
        (ASSIGNEE, True, True, True, True, False),
        (OTHER, False, True, True, True, False),
        (VIEWER, False, False, False, False, False),
    ],
)
def test_permission_matrix(
    actor: U,
    can_edit: bool,
    can_assign: bool,
    can_create: bool,
    can_comment: bool,
    can_delete: bool,
) -> None:
    inc = incident(Status.OPEN)
    assert perms.can_edit(actor, inc) is can_edit
    assert perms.can_assign(actor, inc) is can_assign
    assert perms.can_create(actor) is can_create
    assert perms.can_comment(actor) is can_comment
    assert perms.can_delete(actor, inc) is can_delete


def test_closed_incidents_are_read_only() -> None:
    closed = incident(Status.CLOSED)
    assert not perms.can_edit(ADMIN, closed)
    assert not perms.can_assign(ADMIN, closed)


@pytest.mark.parametrize(
    ("actor", "age_minutes", "allowed"),
    [
        (REPORTER, 5, True),
        (REPORTER, 15, True),
        (REPORTER, 16, False),
        (OTHER, 1, False),
        (ADMIN, 600, True),
        (VIEWER, 1, False),
    ],
)
def test_comment_edit_window(actor: U, age_minutes: int, allowed: bool) -> None:
    comment = C(
        author_id=REPORTER.id if actor is not VIEWER else VIEWER.id,
        created_at=NOW - timedelta(minutes=age_minutes),
    )
    assert perms.can_modify_comment(actor, comment, NOW) is allowed


# ---------------------------------------------------------------- SLA


@pytest.mark.parametrize(
    ("priority", "response_min", "resolution_min"),
    [
        (Priority.CRITICAL, 30, 240),
        (Priority.HIGH, 120, 480),
        (Priority.MEDIUM, 480, 1440),
        (Priority.LOW, 1440, 4320),
    ],
)
def test_due_times_follow_the_sla_table(
    priority: Priority, response_min: int, resolution_min: int
) -> None:
    response, resolution = compute_due(NOW, priority, Settings(_env_file=None))
    assert response == NOW + timedelta(minutes=response_min)
    assert resolution == NOW + timedelta(minutes=resolution_min)


@dataclass
class SlaInc:
    status: Status
    response_due_at: datetime
    resolution_due_at: datetime
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None


def test_sla_on_track() -> None:
    s = sla_state(SlaInc(Status.OPEN, NOW + timedelta(hours=1), NOW + timedelta(hours=4)), NOW)  # type: ignore[arg-type]
    assert (s.response_breached, s.resolution_breached, s.at_risk, s.paused) == (
        False,
        False,
        False,
        False,
    )


def test_sla_at_risk_within_the_last_hour() -> None:
    s = sla_state(SlaInc(Status.IN_PROGRESS, NOW, NOW + timedelta(minutes=59), NOW), NOW)  # type: ignore[arg-type]
    assert s.at_risk and not s.resolution_breached


def test_sla_breached_when_overdue() -> None:
    s = sla_state(SlaInc(Status.OPEN, NOW - timedelta(hours=3), NOW - timedelta(minutes=1)), NOW)  # type: ignore[arg-type]
    assert s.response_breached and s.resolution_breached and not s.at_risk


def test_sla_pauses_when_resolved_and_keeps_the_verdict() -> None:
    on_time = SlaInc(Status.RESOLVED, NOW, NOW + timedelta(hours=1), NOW, resolved_at=NOW)
    late = SlaInc(Status.RESOLVED, NOW, NOW - timedelta(hours=1), NOW, resolved_at=NOW)
    much_later = NOW + timedelta(days=30)  # the clock no longer runs
    assert not sla_state(on_time, much_later).resolution_breached  # type: ignore[arg-type]
    assert sla_state(late, much_later).resolution_breached  # type: ignore[arg-type]
    assert sla_state(on_time, much_later).paused  # type: ignore[arg-type]


# ---------------------------------------------------------------- identifiers


@pytest.mark.parametrize(("raw", "expected"), [("TASK-142", 142), ("inc-7", 7), ("42", 42)])
def test_parse_human_keys(raw: str, expected: int) -> None:
    assert parse_ident(raw) == expected


def test_parse_uuid() -> None:
    value = uuid.uuid4()
    assert parse_ident(str(value)) == value


@pytest.mark.parametrize("raw", ["TASK-", "nope", "TASK-12a"])
def test_parse_garbage_is_404(raw: str) -> None:
    with pytest.raises(NotFound):
        parse_ident(raw)

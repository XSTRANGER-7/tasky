"""Recipient rules as a pure function (spec 9.1) -- no database."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from app.models import NotificationKind, Role
from app.notifications.recipients import mentioned_handles, plan, resolve_mentions

K = NotificationKind


@dataclass(frozen=True)
class P:
    name: str
    role: Role = Role.MEMBER
    is_active: bool = True
    notify_email: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def email(self) -> str:
        return f"{self.name}@demo.io"


REPORTER, ASSIGNEE, WATCHER, ADMIN, VIEWER = (
    P("rita"),
    P("adam"),
    P("walt"),
    P("ada", Role.ADMIN),
    P("sam", Role.VIEWER),
)


def summary(deliveries: list) -> set[tuple[str, NotificationKind, bool]]:  # type: ignore[type-arg]
    return {(d.user.name, d.kind, d.email) for d in deliveries}


def test_assigned() -> None:
    got = plan(
        K.INCIDENT_ASSIGNED,
        actor_id=REPORTER.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[WATCHER],
    )
    assert summary(got) == {
        ("adam", K.INCIDENT_ASSIGNED, True),
        ("walt", K.INCIDENT_ASSIGNED, False),
    }


def test_resolved() -> None:
    got = plan(
        K.INCIDENT_RESOLVED,
        actor_id=ADMIN.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[WATCHER],
    )
    assert summary(got) == {
        ("rita", K.INCIDENT_RESOLVED, True),
        ("walt", K.INCIDENT_RESOLVED, True),
        ("adam", K.INCIDENT_RESOLVED, True),  # resolved by someone else: the assignee hears
    }


def test_updated_reaches_everyone_involved_and_the_admins() -> None:
    boss = P("boss")
    got = plan(
        K.INCIDENT_UPDATED,
        actor_id=REPORTER.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[WATCHER],
        admins=[boss, ASSIGNEE],  # an admin who is also the assignee: one delivery
    )
    assert summary(got) == {
        ("adam", K.INCIDENT_UPDATED, True),
        ("walt", K.INCIDENT_UPDATED, True),
        ("boss", K.INCIDENT_UPDATED, True),
    }


def test_assigned_emails_the_assignee_and_admins_watchers_in_app() -> None:
    boss = P("boss")
    got = plan(
        K.INCIDENT_ASSIGNED,
        actor_id=REPORTER.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[WATCHER],
        admins=[boss],
    )
    assert summary(got) == {
        ("adam", K.INCIDENT_ASSIGNED, True),
        ("boss", K.INCIDENT_ASSIGNED, True),
        ("walt", K.INCIDENT_ASSIGNED, False),
    }


def test_added_emails_only_the_person_added() -> None:
    got = plan(
        K.INCIDENT_ADDED,
        actor_id=REPORTER.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[WATCHER],
        added=[WATCHER],
    )
    assert summary(got) == {("walt", K.INCIDENT_ADDED, True)}


def test_commented_with_a_mention_supersedes_the_generic_notice() -> None:
    got = plan(
        K.INCIDENT_COMMENTED,
        actor_id=ASSIGNEE.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[WATCHER],
        mentioned=[REPORTER],
    )
    assert summary(got) == {("rita", K.MENTIONED, True), ("walt", K.INCIDENT_COMMENTED, True)}


def test_sla_breach_goes_to_assignee_and_admins() -> None:
    got = plan(K.SLA_BREACHED, actor_id=None, reporter=REPORTER, assignee=ASSIGNEE, admins=[ADMIN])
    assert summary(got) == {("adam", K.SLA_BREACHED, True), ("ada", K.SLA_BREACHED, False)}


def test_sla_breach_falls_back_to_the_reporter() -> None:
    got = plan(K.SLA_BREACHED, actor_id=None, reporter=REPORTER, assignee=None, admins=[])
    assert summary(got) == {("rita", K.SLA_BREACHED, True)}


def test_actor_inactive_and_opted_out_rules() -> None:
    gone = P("gone", is_active=False)
    quiet = P("quiet", notify_email=False)
    got = plan(
        K.INCIDENT_RESOLVED,
        actor_id=REPORTER.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[gone, quiet],
    )
    assert summary(got) == {
        ("adam", K.INCIDENT_RESOLVED, True),
        ("quiet", K.INCIDENT_RESOLVED, False),  # opted out of email: in-app only
    }


def test_one_delivery_per_person_and_kind_email_wins() -> None:
    # The assignee is also a watcher: one delivery, and the watcher's email survives.
    got = plan(
        K.INCIDENT_RESOLVED,
        actor_id=None,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[ASSIGNEE],
    )
    assert next(d for d in got if d.user.name == "adam").email is True
    assert len(got) == 2


def test_internal_notes_skip_viewers() -> None:
    got = plan(
        K.INCIDENT_COMMENTED,
        actor_id=ASSIGNEE.id,
        reporter=REPORTER,
        assignee=ASSIGNEE,
        watchers=[VIEWER],
        mentioned=[VIEWER],
        internal=True,
    )
    assert "sam" not in {d.user.name for d in got}


def test_mentioned_kind_is_not_a_starting_point() -> None:
    with pytest.raises(ValueError):
        plan(K.MENTIONED, actor_id=None, reporter=REPORTER, assignee=None)


@pytest.mark.parametrize(
    ("body", "handles"),
    [
        ("@mira please look", {"mira"}),
        ("cc @mira, @jonas.", {"mira", "jonas"}),
        ("(@priya) and [@sam]", {"priya", "sam"}),
        ("mail bob@example.com", set()),
        ("@a too short", set()),
        ("line one\n@max on line two", {"max"}),
    ],
)
def test_mention_parsing(body: str, handles: set[str]) -> None:
    assert mentioned_handles(body) == handles


def test_resolve_mentions_matches_email_local_part() -> None:
    people = [P("mira"), P("jonas"), P("sam")]
    assert [p.name for p in resolve_mentions("@MIRA and @sam", people)] == ["mira", "sam"]

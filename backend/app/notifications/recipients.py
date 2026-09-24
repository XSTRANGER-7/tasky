"""Who gets notified (spec 9.1) -- a pure function, unit-tested without a database.

    Kind                Email                                   In-app
    incident_assigned   the newly assigned, team admins         same + watchers
    incident_updated    assignee, reporter, watchers, admins    same
    incident_resolved   assignee, reporter, watchers, admins    same
    incident_added      the person added                        same
    incident_commented  watchers                                reporter, assignee, watchers
    mentioned           mentioned user                          mentioned user
    sla_breached        assignee (else reporter)                same + the team's admins

"Assignee" means every assignee of the task (it can have several).

Rules: never notify the actor; skip inactive users; email only when notify_email is on
(in-app is always delivered); one delivery per (event, recipient, kind); a mention
supersedes the generic "new comment" for the same person; internal notes never reach
viewers.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.models import NotificationKind, Role

# @handle = the local part of a user's email (mira@demo.io -> @mira). Must follow start or
# whitespace/punctuation so "user@example.com" in a comment is not a mention.
MENTION = re.compile(r"(?:^|(?<=[\s(\[{,;:!?]))@([a-zA-Z0-9._-]{2,64})\b")


class Person(Protocol):
    @property
    def id(self) -> uuid.UUID: ...
    @property
    def email(self) -> str: ...
    @property
    def is_active(self) -> bool: ...
    @property
    def notify_email(self) -> bool: ...


@dataclass(frozen=True)
class Delivery:
    user: Person
    kind: NotificationKind
    email: bool
    in_app: bool


def handle_of(person: Person) -> str:
    return person.email.split("@", 1)[0].lower()


def mentioned_handles(body: str) -> set[str]:
    return {m.group(1).lower().rstrip(".") for m in MENTION.finditer(body)}


def resolve_mentions[P: Person](body: str, people: Iterable[P]) -> list[P]:
    handles = mentioned_handles(body)
    return [p for p in people if handle_of(p) in handles]


class _Plan:
    def __init__(self, actor_id: uuid.UUID | None, internal: bool) -> None:
        self.actor_id = actor_id
        self.internal = internal
        self._by_user: dict[tuple[uuid.UUID, NotificationKind], Delivery] = {}

    def add(self, people: Iterable[Person | None], kind: NotificationKind, *, email: bool) -> None:
        for person in people:
            if person is None or person.id == self.actor_id or not person.is_active:
                continue
            # A User carries its role in the incident's team (``effective_role``); plain
            # test doubles carry ``role``.
            role = getattr(person, "effective_role", None) or getattr(person, "role", None)
            if self.internal and role == Role.VIEWER:
                continue
            key = (person.id, kind)
            prev = self._by_user.get(key)
            wants_email = email and person.notify_email
            self._by_user[key] = Delivery(
                user=person,
                kind=kind,
                email=wants_email or (prev.email if prev else False),
                in_app=True,
            )

    def deliveries(self) -> list[Delivery]:
        return list(self._by_user.values())


def plan(
    kind: NotificationKind,
    *,
    actor_id: uuid.UUID | None,
    reporter: Person,
    assignee: Person | None,
    co_assignees: Sequence[Person] = (),
    watchers: Sequence[Person] = (),
    mentioned: Sequence[Person] = (),
    admins: Sequence[Person] = (),
    added: Sequence[Person] = (),
    internal: bool = False,
) -> list[Delivery]:
    p = _Plan(actor_id, internal)
    everyone_assigned: list[Person | None] = [assignee, *co_assignees]
    if kind == NotificationKind.INCIDENT_ASSIGNED:
        # ``added`` = the people just assigned (several at once); else the lead.
        newly: list[Person | None] = list(added) if added else [assignee]
        p.add([*newly, *admins], kind, email=True)
        p.add(watchers, kind, email=False)
    elif kind in (NotificationKind.INCIDENT_RESOLVED, NotificationKind.INCIDENT_UPDATED):
        # Whoever did it is skipped (the actor); everyone else involved, and the team's
        # admins, hear that the task moved on.
        p.add([*everyone_assigned, reporter, *watchers, *admins], kind, email=True)
    elif kind == NotificationKind.INCIDENT_ADDED:
        p.add(added, kind, email=True)
    elif kind == NotificationKind.INCIDENT_COMMENTED:
        # A mention replaces the generic comment notification for that person.
        mentioned_ids = {m.id for m in mentioned}
        p.add(mentioned, NotificationKind.MENTIONED, email=True)
        p.add([w for w in watchers if w.id not in mentioned_ids], kind, email=True)
        p.add(
            [
                x
                for x in (reporter, *everyone_assigned)
                if x is not None and x.id not in mentioned_ids
            ],
            kind,
            email=False,
        )
    elif kind == NotificationKind.SLA_BREACHED:
        owners = everyone_assigned if assignee else [reporter]
        p.add(owners, kind, email=True)
        p.add(admins, kind, email=False)
    else:  # MENTIONED is produced by INCIDENT_COMMENTED
        raise ValueError(f"plan() does not start from {kind}")
    return p.deliveries()

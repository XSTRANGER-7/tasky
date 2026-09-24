"""Email templates are snapshot-tested (spec 9.7), and user text is escaped.

Snapshots live in tests/snapshots/. To accept a deliberate template change run
``UPDATE_SNAPSHOTS=1 pytest tests/test_email_templates.py`` and review the diff.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models import INCIDENT_KINDS, NotificationKind, Priority, Role, Status
from app.notifications.rendering import render_email

SNAPSHOTS = Path(__file__).parent / "snapshots"
WHEN = datetime(2026, 9, 22, 14, 2, tzinfo=UTC)


@dataclass
class U:
    name: str
    email: str = "x@demo.io"
    role: Role = Role.MEMBER
    id: uuid.UUID = field(default_factory=lambda: uuid.UUID(int=1))


@dataclass
class Inc:
    number: int = 142
    title: str = "Database connection pool exhausted"
    description: str = "`FATAL: remaining connection slots are reserved` since 14:02."
    priority: Priority = Priority.CRITICAL
    status: Status = Status.OPEN


def _render(kind: NotificationKind, **overrides: object):  # type: ignore[no-untyped-def]
    incident = Inc(**overrides)  # type: ignore[arg-type]
    return render_email(
        kind,
        incident,  # type: ignore[arg-type]
        actor=U("Mira Patel"),  # type: ignore[arg-type]
        recipient=U("Jonas Weber"),  # type: ignore[arg-type]
        base_url="https://incident-desk.example.com",
        when=WHEN,
        body="Raised max_connections and added PgBouncer."
        if kind != NotificationKind.INCIDENT_ASSIGNED
        else None,
    )


def _check(name: str, content: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    assert content == path.read_text(encoding="utf-8"), f"{name} changed; see module docstring"


@pytest.mark.parametrize("kind", sorted(INCIDENT_KINDS))
def test_snapshots(kind: NotificationKind) -> None:
    email = _render(kind)
    _check(f"{kind.value}.subject.txt", email.subject + "\n")
    _check(f"{kind.value}.txt", email.text)
    _check(f"{kind.value}.html", email.html)


def test_subjects_follow_the_pattern() -> None:
    assert _render(NotificationKind.INCIDENT_ASSIGNED).subject == (
        "[TASK-142] Assigned to you: Database connection pool exhausted"
    )


def test_links_point_at_the_incident() -> None:
    email = _render(NotificationKind.INCIDENT_ASSIGNED)
    assert "https://incident-desk.example.com/tasks/TASK-142" in email.html
    assert "https://incident-desk.example.com/tasks/TASK-142" in email.text


def test_user_text_is_escaped_in_html_and_cannot_inject_headers() -> None:
    email = _render(
        NotificationKind.INCIDENT_COMMENTED,
        title='<script>alert("x")</script>\r\nBcc: victim@example.com',
    )
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
    assert "\r" not in email.subject and "\n" not in email.subject


def test_snippet_is_capped_at_200_characters() -> None:
    email = render_email(
        NotificationKind.INCIDENT_ASSIGNED,
        Inc(description="x" * 1000),  # type: ignore[arg-type]
        actor=None,
        recipient=U("Jonas"),  # type: ignore[arg-type]
        base_url="http://localhost:5173",
        when=WHEN,
    )
    assert "x" * 199 + "…" in email.text
    assert "x" * 201 not in email.text
    assert "Automatic check" in email.text  # no actor (e.g. the SLA checker)

"""Render notification emails (plain text + HTML) and in-app titles.

User-supplied text (titles, comments, names) is autoescaped in the HTML template and
stripped of CR/LF in subjects, so it can never inject markup or mail headers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.models import Incident, NotificationKind, Priority, Status, User
from app.models.incident import key_for

SNIPPET_CHARS = 200
_TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
    undefined=StrictUndefined,  # a missing variable is a bug, not an empty string
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

PRIORITY_COLOR = {
    Priority.CRITICAL: "#DC2626",
    Priority.HIGH: "#EA580C",
    Priority.MEDIUM: "#CA8A04",
    Priority.LOW: "#64748B",
}
STATUS_LABEL = {
    Status.OPEN: "Open",
    Status.IN_PROGRESS: "In progress",
    Status.RESOLVED: "Resolved",
    Status.CLOSED: "Closed",
}


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str
    headline: str
    summary: str  # short line for the in-app notification body


def _one_line(value: str) -> str:
    return re.sub(r"[\r\n\t]+", " ", value).strip()


def snippet(value: str | None) -> str:
    text = (value or "").strip()
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1].rstrip() + "…"


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _copy(kind: NotificationKind, actor: User | None, key: str, title: str) -> tuple[str, str, str]:
    """(subject, headline, intro) per kind."""
    who = actor.name if actor else "Tasky"
    return {
        NotificationKind.INCIDENT_ASSIGNED: (
            f"[{key}] Assigned to you: {title}",
            "Assigned to you",
            f"{who} assigned this task to you.",
        ),
        NotificationKind.INCIDENT_RESOLVED: (
            f"[{key}] Resolved: {title}",
            "Task resolved",
            f"{who} marked this task as resolved.",
        ),
        NotificationKind.INCIDENT_UPDATED: (
            f"[{key}] Updated by {who}: {title}",
            "Task updated",
            f"{who} made changes to this task:",
        ),
        NotificationKind.INCIDENT_ADDED: (
            f"[{key}] {who} added you: {title}",
            "You were added to a task",
            f"{who} added you to this task. You will now hear about its updates.",
        ),
        NotificationKind.INCIDENT_COMMENTED: (
            f"[{key}] New comment from {who}: {title}",
            "New comment",
            f"{who} commented:",
        ),
        NotificationKind.MENTIONED: (
            f"[{key}] {who} mentioned you: {title}",
            "You were mentioned",
            f"{who} mentioned you in a comment:",
        ),
        NotificationKind.SLA_BREACHED: (
            f"[{key}] SLA breached: {title}",
            "Resolution SLA breached",
            "This task has passed its resolution deadline and is still open.",
        ),
    }[kind]


def render_email(
    kind: NotificationKind,
    incident: Incident,
    *,
    actor: User | None,
    recipient: User,
    base_url: str,
    when: datetime,
    body: str | None = None,
    assigned: Sequence[User] = (),
) -> RenderedEmail:
    key = key_for(incident.number)
    title = _one_line(incident.title)
    subject, headline, intro = _copy(kind, actor, key, title)
    if (
        kind == NotificationKind.INCIDENT_ASSIGNED
        and assigned
        and all(u.id != recipient.id for u in assigned)
    ):
        # A copy for someone else (a team admin): say who it went to, not "to you".
        who = actor.name if actor else "Tasky"
        names = _names([u.name for u in assigned])
        subject = f"[{key}] Assigned to {names}: {title}"
        headline = "Task assigned"
        intro = f"{who} assigned this task to {names}."
    elif kind == NotificationKind.INCIDENT_ASSIGNED and len(assigned) > 1:
        others = _names([u.name for u in assigned if u.id != recipient.id])
        intro = f"{intro[:-1]}, together with {others}."

    excerpt = snippet(body if body is not None else incident.description)
    context = {
        "subject": _one_line(subject),
        "headline": headline,
        "intro": intro,
        "key": key,
        "title": title,
        "priority_label": incident.priority.value.title(),
        "priority_color": PRIORITY_COLOR[incident.priority],
        "status_label": STATUS_LABEL[incident.status],
        "snippet": excerpt,
        "url": f"{base_url.rstrip('/')}/tasks/{key}",
        "actor_line": f"By {actor.name}" if actor else "Automatic check",
        "when": when.strftime("%d %b %Y, %H:%M UTC"),
        "recipient_name": recipient.name,
    }
    return RenderedEmail(
        subject=_one_line(subject)[:300],
        text=_env.get_template("email.txt.j2").render(context),
        html=_env.get_template("email.html.j2").render(context),
        headline=headline,
        summary=_one_line(f"{intro} {excerpt}")[:400],
    )


# ---------------------------------------------------------------- non-incident messages

GENERIC_FOOTER = "Tasky sends this about your account and teams."


def render_message(
    *,
    subject: str,
    headline: str,
    title: str,
    intro: str,
    cta: str,
    url: str,
    recipient: User,
    when: datetime,
    quote: str | None = None,
    note: str | None = None,
    footer: str = GENERIC_FOOTER,
) -> RenderedEmail:
    """Emails that are not about an incident: team requests, password resets."""
    context = {
        "subject": _one_line(subject),
        "headline": headline,
        "title": _one_line(title),
        "intro": intro,
        "quote": snippet(quote) if quote else "",
        "cta": cta,
        "url": url,
        "note": note or "",
        "when": when.strftime("%d %b %Y, %H:%M UTC"),
        "footer": footer,
        "recipient_name": recipient.name,
    }
    return RenderedEmail(
        subject=_one_line(subject)[:300],
        text=_env.get_template("message.txt.j2").render(context),
        html=_env.get_template("message.html.j2").render(context),
        headline=headline,
        summary=_one_line(f"{intro} {snippet(quote) if quote else ''}")[:400],
    )

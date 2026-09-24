"""Transactional live-update publishing via Postgres NOTIFY.

Services call :func:`queue` while they work; just before the transaction commits, every
queued message is sent with ``pg_notify`` *inside that transaction*. Postgres delivers
NOTIFY only when the transaction commits -- a rolled-back change never broadcasts, and
every API process (and the worker) sees the same stream without a separate message bus.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.orm import Session

CHANNEL = "incident_desk"
_KEY = "realtime_outbox"


def queue(session: Any, message: dict[str, Any]) -> None:
    """Queue a message on an (async or sync) session; sent on commit, dropped on rollback."""
    sync: Session = getattr(session, "sync_session", session)
    pending: list[dict[str, Any]] = sync.info.setdefault(_KEY, [])
    if message not in pending:  # several events on one incident -> one "updated"
        pending.append(message)


@event.listens_for(Session, "before_commit")
def _flush_notifications(session: Session) -> None:
    pending: list[dict[str, Any]] = session.info.pop(_KEY, [])
    for message in pending:
        session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": CHANNEL, "payload": json.dumps(message, separators=(",", ":"))},
        )


@event.listens_for(Session, "after_rollback")
def _discard(session: Session) -> None:
    session.info.pop(_KEY, None)

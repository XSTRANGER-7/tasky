"""Outbox delivery: claim due rows, send, record the outcome (spec 9.5).

* Rows are claimed with ``FOR UPDATE SKIP LOCKED``: several workers can run side by side
  and never pick the same row.
* A batch is one transaction. If the process dies mid-batch nothing is marked and the
  rows are retried -- delivery is at-least-once, never at-most-once.
* Failures back off 1, 2, 4, 8 minutes; the 5th failure marks the row ``failed`` for an
  admin to retry. The recipient is re-checked before sending (deactivated -> failed).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import NotificationKind, NotificationOutbox, OutboxStatus
from app.notifications.senders import Email, EmailSender, SendError

log = get_logger(__name__)

MAX_ATTEMPTS = 5
# Their bodies hold a live credential (the reset link): once sent, keep only the subject.
REDACT_AFTER_SEND = frozenset({NotificationKind.PASSWORD_RESET})
REDACTED = "[redacted after delivery]"


def backoff(attempts: int) -> timedelta:
    """Delay before the next try after ``attempts`` failures: 1, 2, 4, 8, 16 minutes."""
    return timedelta(minutes=2 ** (attempts - 1))


@dataclass
class BatchResult:
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0


async def process_batch(
    session: AsyncSession, sender: EmailSender, *, limit: int = 20
) -> BatchResult:
    now = utcnow()
    rows = (
        await session.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == OutboxStatus.PENDING,
                NotificationOutbox.next_attempt_at <= now,
            )
            .order_by(NotificationOutbox.next_attempt_at, NotificationOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=NotificationOutbox)
            .options(joinedload(NotificationOutbox.recipient))
        )
    ).all()

    result = BatchResult(claimed=len(rows))
    for row in rows:
        started = time.perf_counter()
        if not row.recipient.is_active:
            row.status = OutboxStatus.FAILED
            row.last_error = "recipient deactivated before delivery"
            result.failed += 1
            log.info("outbox_skipped", outbox_id=str(row.id), reason="recipient_inactive")
            continue
        try:
            await sender.send(
                Email(
                    to=row.recipient_email,
                    subject=row.subject,
                    text=row.body_text,
                    html=row.body_html,
                )
            )
        except SendError as exc:
            row.attempts += 1
            row.last_error = str(exc)[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = OutboxStatus.FAILED
                result.failed += 1
                outcome = "failed"
            else:
                row.next_attempt_at = utcnow() + backoff(row.attempts)
                result.retried += 1
                outcome = "retry"
            log.warning(
                "outbox_send_failed",
                outbox_id=str(row.id),
                kind=row.kind.value,
                attempt=row.attempts,
                result=outcome,
                error=row.last_error,
            )
        else:
            row.status = OutboxStatus.SENT
            row.sent_at = utcnow()
            row.attempts += 1
            row.last_error = None
            if row.kind in REDACT_AFTER_SEND:
                row.body_text = row.body_html = REDACTED
            result.sent += 1
            log.info(
                "outbox_sent",
                outbox_id=str(row.id),
                kind=row.kind.value,
                attempt=row.attempts,
                provider=sender.name,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
    await session.commit()
    return result


async def counts(session: AsyncSession, team_id: uuid.UUID | None = None) -> dict[str, int]:
    """Rows per status: everywhere, or for one team's mail only."""
    stmt = select(NotificationOutbox.status, func.count()).group_by(NotificationOutbox.status)
    if team_id is not None:
        stmt = stmt.where(NotificationOutbox.team_id == team_id)
    rows = await session.execute(stmt)
    out = {s.value: 0 for s in OutboxStatus}
    for status, n in rows:
        out[status.value] = int(n)
    return out

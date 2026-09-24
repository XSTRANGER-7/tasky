"""Outbox delivery and the worker loop (spec 9.5, 16): send, retry with 1-2-4-8 minute
backoff, fail after 5, SKIP LOCKED with two workers, inactive recipients, the loop."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.base import utcnow
from app.models import NotificationOutbox, OutboxStatus, User
from app.notifications import delivery
from app.notifications.delivery import MAX_ATTEMPTS, backoff, process_batch
from app.notifications.worker import Worker
from tests.conftest import CreateIncident, Person
from tests.fakes import FakeSender

pytestmark = pytest.mark.db
Db = async_sessionmaker[AsyncSession]


def test_backoff_schedule() -> None:
    assert [backoff(n) for n in range(1, 6)] == [timedelta(minutes=m) for m in (1, 2, 4, 8, 16)]


@pytest.fixture(autouse=True)
async def _one_email_per_assignment(people: dict[str, Person], db: Db) -> None:
    """These tests are about delivery, not recipients (test_notifications covers who gets
    what): the team's admin, who is also emailed about every assignment, has email off,
    so each assignment queues exactly one email, to the assignee."""
    async with db() as s:
        await s.execute(
            update(User).where(User.id == people["admin"].id).values(notify_email=False)
        )
        await s.commit()


@pytest.fixture
async def queued(
    create_incident: CreateIncident, people: dict[str, Person], db: Db
) -> list[NotificationOutbox]:
    """Three pending emails (three incidents assigned to Max by Mira)."""
    for n in range(3):
        await create_incident(title=f"Queued incident {n}", assignee_id=str(people["max"].id))
    async with db() as s:
        return list((await s.scalars(select(NotificationOutbox))).all())


async def _rows(db: Db) -> list[NotificationOutbox]:
    async with db() as s:
        return list(
            (
                await s.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at))
            ).all()
        )


async def _make_due(db: Db) -> None:
    async with db() as s:
        await s.execute(update(NotificationOutbox).values(next_attempt_at=utcnow()))
        await s.commit()


async def test_worker_sends_and_marks_sent(queued: list[NotificationOutbox], db: Db) -> None:
    sender = FakeSender()

    async with db() as s:
        result = await process_batch(s, sender)

    assert (result.claimed, result.sent) == (3, 3)
    assert {e.to for e in sender.sent} == {"max@example.com"}
    assert all(
        e.subject.startswith("[TASK-") and "Assigned to you" in e.subject for e in sender.sent
    )
    rows = await _rows(db)
    assert {r.status for r in rows} == {OutboxStatus.SENT}
    assert all(r.sent_at is not None and r.attempts == 1 for r in rows)


async def test_sent_rows_are_never_sent_again(queued: list[NotificationOutbox], db: Db) -> None:
    sender = FakeSender()
    async with db() as s:
        await process_batch(s, sender)
    async with db() as s:
        again = await process_batch(s, sender)

    assert again.claimed == 0
    assert len(sender.sent) == 3


async def test_retries_with_backoff_then_fails_after_five(
    create_incident: CreateIncident, people: dict[str, Person], db: Db
) -> None:
    await create_incident(assignee_id=str(people["max"].id))
    sender = FakeSender(fail_times=100)
    delays = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        before = utcnow()
        async with db() as s:
            result = await process_batch(s, sender)
        assert result.claimed == 1
        (row,) = await _rows(db)
        assert row.attempts == attempt
        assert row.last_error == f"fake failure {attempt}"
        if attempt < MAX_ATTEMPTS:
            assert row.status == OutboxStatus.PENDING
            delays.append(round((row.next_attempt_at - before).total_seconds() / 60))
            async with db() as s:  # not due yet: the worker must leave it alone
                assert (await process_batch(s, sender)).claimed == 0
            await _make_due(db)

    (row,) = await _rows(db)
    assert row.status == OutboxStatus.FAILED
    assert delays == [1, 2, 4, 8]
    assert sender.calls == MAX_ATTEMPTS


async def test_transient_failure_then_success(
    create_incident: CreateIncident, people: dict[str, Person], db: Db
) -> None:
    await create_incident(assignee_id=str(people["max"].id))
    sender = FakeSender(fail_times=1)

    async with db() as s:
        await process_batch(s, sender)
    await _make_due(db)
    async with db() as s:
        await process_batch(s, sender)

    (row,) = await _rows(db)
    assert row.status == OutboxStatus.SENT
    assert row.attempts == 2
    assert row.last_error is None


async def test_two_workers_never_double_send(
    create_incident: CreateIncident, people: dict[str, Person], db: Db
) -> None:
    for n in range(8):
        await create_incident(title=f"Parallel incident {n}", assignee_id=str(people["max"].id))
    sender = FakeSender(delay=0.05)  # slow sends keep the row locks held

    async def one_worker() -> int:
        async with db() as s:
            return (await process_batch(s, sender, limit=5)).sent

    first, second = await asyncio.gather(one_worker(), one_worker())

    assert first + second == 8
    assert first > 0 and second > 0  # SKIP LOCKED let both make progress
    subjects = [e.subject for e in sender.sent]
    assert len(subjects) == len(set(subjects)) == 8


async def test_deactivated_recipient_is_not_emailed(
    queued: list[NotificationOutbox], people: dict[str, Person], db: Db
) -> None:
    async with db() as s:
        await s.execute(update(User).where(User.id == people["max"].id).values(is_active=False))
        await s.commit()
    sender = FakeSender()

    async with db() as s:
        result = await process_batch(s, sender)

    assert sender.sent == []
    assert result.failed == 3
    assert {r.last_error for r in await _rows(db)} == {"recipient deactivated before delivery"}


async def test_counts(queued: list[NotificationOutbox], db: Db) -> None:
    async with db() as s:
        assert await delivery.counts(s) == {"pending": 3, "sent": 0, "failed": 0}


# ---------------------------------------------------------------- the loop


async def test_worker_drains_full_batches(
    queued: list[NotificationOutbox], settings: Settings, db: Db
) -> None:
    sender = FakeSender()
    worker = Worker(
        settings.model_copy(update={"worker_batch_size": 1}), sender=sender, sessionmaker=db
    )

    sent = await worker.deliver()

    assert sent == 3  # kept going while batches came back full


async def test_worker_loop_stops_promptly_and_beats(
    queued: list[NotificationOutbox], settings: Settings, db: Db
) -> None:
    sender = FakeSender()
    worker = Worker(
        settings.model_copy(update={"worker_poll_seconds": 60}), sender=sender, sessionmaker=db
    )

    task = asyncio.create_task(worker.run())
    for _ in range(50):
        if len(sender.sent) == 3:
            break
        await asyncio.sleep(0.05)
    worker.stop()
    await asyncio.wait_for(task, timeout=2)  # does not wait out the 60 s interval

    assert len(sender.sent) == 3
    assert worker.ticks == 1


async def test_worker_survives_a_failing_tick(
    settings: Settings, db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker(
        settings.model_copy(update={"worker_poll_seconds": 0.01}),
        sender=FakeSender(),
        sessionmaker=db,
    )
    calls = 0

    async def flaky_heartbeat() -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise ConnectionError("db restarting")

    monkeypatch.setattr(worker, "heartbeat", flaky_heartbeat)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    worker.stop()
    await asyncio.wait_for(task, timeout=2)

    assert calls > 2
    assert worker.ticks == calls - 2

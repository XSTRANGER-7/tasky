"""Notification worker: ``python -m app.notifications.worker``.

Every WORKER_POLL_SECONDS: write a heartbeat, deliver one outbox batch (repeating
immediately while batches come back full). Every SLA_CHECK_SECONDS: run the SLA breach
checker. Exits cleanly on SIGTERM/SIGINT; a failing tick is logged and retried on the next
one, never allowed to crash the loop. ``RUN_WORKER_IN_API=true`` runs the same loop as a
task inside the API process (single-service hosts).
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
import sys
import time
from collections.abc import Callable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import utcnow
from app.db.session import dispose_engine, get_sessionmaker
from app.models import WorkerHeartbeat
from app.notifications import delivery, sla_checker
from app.notifications.senders import EmailSender, build_sender
from app.services import supabase_auth

log = get_logger("app.worker")
HEARTBEAT_NAME = "notifications"


class Worker:
    def __init__(
        self,
        settings: Settings,
        *,
        sender: EmailSender | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.sender = sender or build_sender(settings)
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._stop = asyncio.Event()
        self._last_sla_check = -float("inf")
        self._last_supabase_copy = -float("inf")
        self.ticks = 0
        self.sent = 0

    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker or get_sessionmaker()

    def stop(self) -> None:
        self._stop.set()

    async def heartbeat(self) -> None:
        async with self.sessions() as session:
            info = {"host": socket.gethostname(), "version": __version__, "sent": self.sent}
            stmt = insert(WorkerHeartbeat).values(name=HEARTBEAT_NAME, beat_at=utcnow(), info=info)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.name],
                    set_={"beat_at": stmt.excluded.beat_at, "info": stmt.excluded.info},
                )
            )
            await session.commit()

    async def deliver(self) -> int:
        """Drain due rows: keep taking batches while they come back full."""
        total = 0
        while not self._stop.is_set():
            async with self.sessions() as session:
                result = await delivery.process_batch(
                    session, self.sender, limit=self.settings.worker_batch_size
                )
            total += result.sent
            if result.claimed:
                log.info("outbox_batch", **vars(result))
            if result.claimed < self.settings.worker_batch_size:
                break
        self.sent += total
        return total

    async def check_sla(self, *, force: bool = False) -> int:
        now = self._clock()
        if not force and now - self._last_sla_check < self.settings.sla_check_seconds:
            return 0
        self._last_sla_check = now
        async with self.sessions() as session:
            return await sla_checker.check(session, self.settings)

    async def copy_accounts(self, *, force: bool = False) -> int:
        """Copy accounts missing from Supabase Auth (new ones, earlier failures)."""
        if not self.settings.supabase_auth_copy_enabled:
            return 0
        now = self._clock()
        if not force and now - self._last_supabase_copy < self.settings.supabase_auth_sync_seconds:
            return 0
        self._last_supabase_copy = now
        async with self.sessions() as session:
            return await supabase_auth.copy_missing(session, self.settings)

    async def tick(self) -> None:
        await self.heartbeat()
        await self.deliver()
        await self.check_sla()
        await self.copy_accounts()
        self.ticks += 1

    async def run(self) -> None:
        interval = self.settings.worker_poll_seconds
        log.info(
            "worker_started",
            version=__version__,
            poll_seconds=interval,
            provider=self.sender.name,
            sla_check_seconds=self.settings.sla_check_seconds,
        )
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                # Never die on a transient failure (DB restart, network blip); the next
                # tick retries. Crash-looping would only add restart noise.
                log.exception("worker_tick_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
        log.info("worker_stopped", ticks=self.ticks, sent=self.sent)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    worker = Worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Not supported by Windows event loops; Ctrl+C still raises there.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run()
    finally:
        await dispose_engine()


def run() -> None:
    # psycopg's async mode cannot use Windows' default ProactorEventLoop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(main(), loop_factory=loop_factory)


if __name__ == "__main__":
    run()

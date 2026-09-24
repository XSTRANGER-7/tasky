"""Check every outside connection with the settings in .env, and say what is wrong.

    python -m app.scripts.check_integrations
    python -m app.scripts.check_integrations --send-test-email you@company.com

Checks the database (connection, migrations at head, data present), the worker
heartbeat, email (SMTP login or API key; optionally a real test email), attachment
storage (write, read back, delete) and the AI provider (one tiny call). Nothing is
left behind. Exit code 1 if anything failed, so it also works in a deploy script.
"""

from __future__ import annotations

import argparse
import asyncio
import smtplib
import ssl
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.ai.providers import AIUnavailable, InvalidOutput, Prompt, build_provider
from app.core.config import Settings, get_settings
from app.db.session import dispose_engine, get_sessionmaker
from app.models import Incident, User
from app.notifications.senders import Email, SendError, build_sender
from app.services import supabase_auth
from app.services.worker_status import worker_status
from app.storage import LocalStorage, StorageError, build_storage

BACKEND = Path(__file__).resolve().parents[2]
OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "
failures = 0


def report(status: str, area: str, message: str) -> None:
    global failures
    if status == FAIL:
        failures += 1
    print(f"[{status}] {area:<9} {message}")


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


async def check_database(settings: Settings) -> bool:
    try:
        async with get_sessionmaker()() as session:
            version = await session.scalar(text("SHOW server_version"))
            current = await session.scalar(text("SELECT version_num FROM alembic_version"))
            users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
            incidents = int(await session.scalar(select(func.count()).select_from(Incident)) or 0)
            worker = await worker_status(session, settings)
    except Exception as exc:  # any failure here is the finding
        report(FAIL, "database", f"{_redact(settings.database_url)}: {type(exc).__name__}: {exc}")
        return False
    report(OK, "database", f"PostgreSQL {version} at {_redact(settings.database_url)}")

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if current == head:
        report(OK, "database", f"migrations at head ({head})")
    else:
        report(
            FAIL, "database", f"migrations at {current}, head is {head}: run `alembic upgrade head`"
        )

    if users == 0:
        report(
            WARN,
            "database",
            f"no users yet: sign up at {settings.app_base_url}/register and create a team",
        )
    else:
        report(OK, "database", f"{users} users, {incidents} incidents")

    if worker.status == "ok":
        report(OK, "worker", f"heartbeat {worker.seconds_since_beat:.0f}s ago")
    else:
        report(
            WARN,
            "worker",
            f"{worker.status}: start `python -m app.notifications.worker` "
            "(emails queue until then)",
        )
    return True


def _smtp_login(settings: Settings) -> None:
    context = ssl.create_default_context()
    smtp: smtplib.SMTP = (
        smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
        if settings.smtp_ssl
        else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    )
    with smtp:
        if settings.smtp_starttls and not settings.smtp_ssl:
            smtp.starttls(context=context)
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)


async def check_email(settings: Settings, send_to: str | None) -> None:
    provider = settings.email_provider
    if provider == "console":
        report(
            WARN,
            "email",
            "EMAIL_PROVIDER=console only logs emails; set smtp, brevo or resend to deliver",
        )
    elif provider == "smtp":
        where = f"{settings.smtp_host}:{settings.smtp_port}"
        try:
            await asyncio.to_thread(_smtp_login, settings)
            auth = "logged in" if settings.smtp_username else "no login configured"
            report(OK, "email", f"SMTP {where}: connected, {auth}")
        except (OSError, smtplib.SMTPException) as exc:
            report(FAIL, "email", f"SMTP {where}: {type(exc).__name__}: {exc}")
            return
    else:
        url, headers = (
            ("https://api.brevo.com/v3/account", {"api-key": settings.brevo_api_key or ""})
            if provider == "brevo"
            else (
                "https://api.resend.com/domains",
                {"Authorization": f"Bearer {settings.resend_api_key or ''}"},
            )
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            report(FAIL, "email", f"{provider}: {type(exc).__name__}")
            return
        if res.status_code == 200:
            report(OK, "email", f"{provider}: API key accepted")
        elif provider == "resend" and res.status_code in (401, 403):
            # "Sending access" keys cannot list domains; only a real send proves them.
            if not send_to:
                report(WARN, "email", "resend: key cannot read domains; use --send-test-email")
                return
        else:
            report(FAIL, "email", f"{provider}: API key rejected (HTTP {res.status_code})")
            return

    if send_to:
        sender = build_sender(settings)
        email = Email(
            to=send_to,
            subject="[Tasky] Integration check",
            text=f"If you can read this, email from {settings.app_name} works.\n",
            html=f"<p>If you can read this, email from <b>{settings.app_name}</b> works.</p>",
        )
        try:
            await sender.send(email)
            report(OK, "email", f"test email sent to {send_to} from {settings.email_from}")
        except SendError as exc:
            report(FAIL, "email", f"sending to {send_to}: {exc}")


async def check_storage(settings: Settings) -> None:
    try:
        storage = build_storage(settings)
    except StorageError as exc:
        report(FAIL, "storage", str(exc))
        return
    key = f"_integration-check/{uuid.uuid4().hex}.txt"
    payload = f"incident-desk check {time.time()}".encode()
    try:
        await storage.put(key, payload, "text/plain")
        if isinstance(storage, LocalStorage):
            back = storage.read(key)
            where = f"local disk {storage.root}"
        else:
            url = storage.download_url(
                key, filename="check.txt", content_type="text/plain", inline=False
            )
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(url)
            back = res.content if res.status_code == 200 else b""
            where = f"S3 bucket {settings.s3_bucket} at {settings.s3_endpoint}"
        await storage.delete(key)
    except (StorageError, OSError, httpx.HTTPError) as exc:
        report(FAIL, "storage", f"{type(exc).__name__}: {exc}")
        return
    if back == payload:
        report(OK, "storage", f"{where}: write, read back and delete all work")
    else:
        report(FAIL, "storage", f"{where}: wrote a file but could not read it back")
    if isinstance(storage, LocalStorage) and settings.is_production:
        report(WARN, "storage", "local disk in production: files live and die with this server")


class _Ping(BaseModel):
    ok: bool


async def check_ai(settings: Settings) -> None:
    if settings.llm_provider == "none":
        report(WARN, "ai", "LLM_PROVIDER=none: AI features are off (the app works without them)")
        return
    if settings.llm_provider == "rules":
        report(OK, "ai", "rule-based engine: offline, nothing to connect")
        return
    provider = build_provider(settings)
    assert provider is not None  # noqa: S101 - llm_provider is a real provider here
    prompt = Prompt("check-v1", 'Reply with the JSON object {"ok": true} and nothing else.', "ping")
    started = time.perf_counter()
    try:
        await provider.complete(prompt, _Ping)
    except (AIUnavailable, InvalidOutput) as exc:
        report(FAIL, "ai", f"{settings.llm_provider} ({provider.model}): {exc}")
        return
    ms = int((time.perf_counter() - started) * 1000)
    report(OK, "ai", f"{settings.llm_provider} ({provider.model}) answered in {ms} ms")


async def check_supabase_auth(settings: Settings) -> None:
    if not settings.supabase_auth_copy_enabled:
        report(WARN, "supabase", "account copy to Supabase Auth is off (optional)")
        return
    good, message = await supabase_auth.check(settings)
    report(OK if good else FAIL, "supabase", f"Auth user copy: {message}")


async def run(send_to: str | None) -> int:
    settings = get_settings()
    print(f"Tasky integration check (APP_ENV={settings.app_env})\n")
    checks: list[Callable[[], Awaitable[object]]] = [
        lambda: check_database(settings),
        lambda: check_email(settings, send_to),
        lambda: check_storage(settings),
        lambda: check_ai(settings),
        lambda: check_supabase_auth(settings),
    ]
    for check in checks:
        await check()
    await dispose_engine()
    print("\nAll good." if failures == 0 else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--send-test-email", metavar="ADDRESS", help="also send a real email")
    args = parser.parse_args()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(run(args.send_test_email), loop_factory=loop_factory))


if __name__ == "__main__":
    main()

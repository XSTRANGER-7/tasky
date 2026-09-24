"""Copy accounts into Supabase Auth so they show under Authentication -> Users.

Copies only: this app keeps doing its own sign-in (passwords, Google, sessions), so no
password is ever sent and a copy cannot be used to log in. Changes or deletions made in
the Supabase dashboard do not flow back. ``users.supabase_auth_id`` records which
accounts are copied; anything missing (new sign-ups, a failed call, accounts that existed
before this was switched on) is picked up by ``copy_missing``, which the API runs right
after a sign-up and the worker runs every SUPABASE_AUTH_SYNC_SECONDS.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.models import User

log = get_logger(__name__)

BATCH = 50
TIMEOUT = httpx.Timeout(10.0)


class SupabaseAuthError(Exception):
    pass


def _client(settings: Settings, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    key = settings.supabase_service_role_key or ""
    return httpx.AsyncClient(
        base_url=f"{(settings.supabase_url or '').rstrip('/')}/auth/v1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=TIMEOUT,
        transport=transport,
    )


def _payload(user: User) -> dict[str, Any]:
    providers = (["google"] if user.google_sub else []) + (["email"] if user.password_hash else [])
    return {
        "email": user.email,
        "email_confirm": True,  # the app already verified it (Google) or owns the sign-up
        "user_metadata": {"name": user.name, "full_name": user.name},
        "app_metadata": {
            "provider": providers[0] if providers else "email",
            "providers": providers or ["email"],
            "incident_desk_user_id": str(user.id),
        },
    }


async def _find_by_email(client: httpx.AsyncClient, email: str) -> uuid.UUID | None:
    """The copy already exists (an earlier call timed out after succeeding, or it was made
    by hand): find its id by paging through the admin user list."""
    wanted = email.lower()
    for page in range(1, 101):
        r = await client.get("/admin/users", params={"page": page, "per_page": 200})
        if r.status_code != 200:
            raise SupabaseAuthError(f"list users: HTTP {r.status_code}")
        users = r.json().get("users", [])
        for item in users:
            if str(item.get("email", "")).lower() == wanted:
                return uuid.UUID(item["id"])
        if len(users) < 200:
            return None
    return None


async def copy_user(client: httpx.AsyncClient, user: User) -> uuid.UUID:
    """Create the account in Supabase Auth, or adopt the copy that is already there."""
    r = await client.post("/admin/users", json=_payload(user))
    if r.status_code in (200, 201):
        return uuid.UUID(r.json()["id"])
    body = r.text.lower()
    if r.status_code == 422 and ("email_exists" in body or "already been registered" in body):
        found = await _find_by_email(client, user.email)
        if found is not None:
            return found
    raise SupabaseAuthError(f"create user: HTTP {r.status_code}: {r.text[:200]}")


async def copy_missing(
    session: AsyncSession,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Copy up to BATCH accounts that have no Supabase Auth copy yet. Returns how many
    were copied; a failure on one account is logged and retried on the next run."""
    if not settings.supabase_auth_copy_enabled:
        return 0
    users = (
        await session.scalars(
            select(User)
            .where(User.supabase_auth_id.is_(None), User.is_active.is_(True))
            .order_by(User.created_at)
            .limit(BATCH)
        )
    ).all()
    if not users:
        return 0
    copied = 0
    async with _client(settings, transport) as client:
        for user in users:
            try:
                user.supabase_auth_id = await copy_user(client, user)
            except (SupabaseAuthError, httpx.HTTPError, KeyError, ValueError) as exc:
                log.warning("supabase_auth_copy_failed", user_id=str(user.id), error=str(exc))
                continue
            copied += 1
            await session.commit()  # keep each success even if a later one fails
            log.info("supabase_auth_copied", user_id=str(user.id))
    return copied


async def copy_missing_now(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Background task after a sign-up: never raises (the worker retries anything left)."""
    try:
        async with sessionmaker() as session:
            await copy_missing(session, settings)
    except Exception:
        log.exception("supabase_auth_copy_task_failed")


async def check(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[bool, str]:
    """For check_integrations: can the key read Supabase Auth's user list?"""
    if not settings.supabase_auth_copy_enabled:
        return False, "off (set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)"
    try:
        async with _client(settings, transport) as client:
            r = await client.get("/admin/users", params={"page": 1, "per_page": 1})
    except httpx.HTTPError as exc:
        return False, f"unreachable: {exc}"
    if r.status_code == 200:
        return True, "service key accepted"
    return False, f"HTTP {r.status_code} (is it the service_role / secret key?)"

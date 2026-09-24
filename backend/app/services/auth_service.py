"""Authentication use cases: register, login, refresh (rotation + reuse detection), logout,
forgot/reset password, and sign-in with Google.

Each public function is one transaction and commits it. Routers only translate HTTP.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, InvalidInput, PermissionDenied, Unauthenticated
from app.core.logging import get_logger
from app.core.security import (
    AccessToken,
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    hash_reset_token,
    new_refresh_token,
    new_reset_token,
    refresh_expiry,
    verify_password,
)
from app.db.base import utcnow
from app.models import NotificationKind, PasswordResetToken, RefreshToken, TeamRole, User
from app.notifications.rendering import render_message
from app.repositories import team_repo, user_repo
from app.services.google_oauth import GoogleError, GoogleProfile
from app.services.notification_service import notify_user

log = get_logger(__name__)

# Deterministic, accessible avatar colours (readable white initials in both themes).
AVATAR_COLORS = (
    "#6E8BFF", "#3DDC97", "#FF9F43", "#F06292",
    "#4DD0E1", "#9575CD", "#E57373", "#81C784",
)  # fmt: skip


@dataclass(frozen=True)
class AuthSession:
    """Result of login/refresh: what the client gets, plus the cookie value."""

    user: User
    access: AccessToken
    refresh_token: str
    refresh_token_id: uuid.UUID


def avatar_color_for(email: str) -> str:
    digest = hashlib.sha256(email.lower().encode()).digest()
    return AVATAR_COLORS[digest[0] % len(AVATAR_COLORS)]


async def register(
    session: AsyncSession,
    settings: Settings,
    *,
    name: str,
    email: str,
    password: str,
    actor: User | None,
) -> User:
    """Public sign-up when ALLOW_SELF_REGISTER; otherwise only the admin of some team may
    create an account (for someone they then add to their team). New accounts belong to
    no team: they create one or ask to join one."""
    if not settings.allow_self_register:
        admins_a_team = actor is not None and any(
            role == TeamRole.ADMIN for _, role in await team_repo.teams_of_user(session, actor.id)
        )
        if not admins_a_team:
            raise PermissionDenied(
                "Self-registration is disabled; ask a team admin to create your account"
            )

    if await user_repo.get_user_by_email(session, email) is not None:
        raise Conflict("An account with this email already exists", code="email_taken")

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        avatar_color=avatar_color_for(email),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:  # lost a race with a concurrent sign-up
        await session.rollback()
        raise Conflict("An account with this email already exists", code="email_taken") from exc
    log.info("user_registered", user_id=str(user.id), by=str(actor.id) if actor else None)
    return user


async def login(
    session: AsyncSession, settings: Settings, *, email: str, password: str
) -> AuthSession:
    user = await user_repo.get_user_by_email(session, email)
    valid, new_hash = verify_password(password, user.password_hash if user else None)
    if user is None or not valid:
        log.info("login_failed", reason="invalid_credentials")
        raise Unauthenticated("Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise PermissionDenied("This account has been deactivated", code="account_disabled")
    if new_hash:
        user.password_hash = new_hash  # transparent argon2 parameter upgrade

    result = await _issue(session, settings, user)
    await session.commit()
    log.info("login_succeeded", user_id=str(user.id))
    return result


async def refresh(session: AsyncSession, settings: Settings, *, token: str | None) -> AuthSession:
    """Rotate: the presented token is revoked and replaced. Presenting an already-revoked
    token means it was stolen or replayed, so every session of that user is revoked."""
    if not token:
        raise Unauthenticated("No refresh token", code="refresh_missing")

    now = utcnow()
    row = await user_repo.get_refresh_token_for_update(session, hash_refresh_token(token))
    if row is None:
        raise Unauthenticated("Invalid refresh token", code="refresh_invalid")

    if row.revoked_at is not None:
        revoked = await user_repo.revoke_all_refresh_tokens(session, row.user_id, at=now)
        await session.commit()
        log.warning("refresh_token_reuse_detected", user_id=str(row.user_id), revoked=revoked)
        raise Unauthenticated("Refresh token already used", code="refresh_reused")

    if row.expires_at <= now:
        raise Unauthenticated("Refresh token expired", code="refresh_expired")

    user = await user_repo.get_user(session, row.user_id)
    if user is None or not user.is_active:
        row.revoked_at = now
        await session.commit()
        raise Unauthenticated("Account unavailable", code="account_disabled")

    result = await _issue(session, settings, user)
    row.revoked_at = now
    row.replaced_by_id = result.refresh_token_id
    await session.commit()
    return result


async def logout(session: AsyncSession, *, token: str | None) -> None:
    """Idempotent: an unknown or already-revoked token is not an error."""
    if not token:
        return
    row = await user_repo.get_refresh_token_for_update(session, hash_refresh_token(token))
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
        await session.commit()
        log.info("logout", user_id=str(row.user_id))


async def authenticate(session: AsyncSession, settings: Settings, token: str) -> User:
    """Resolve a bearer token to an active user. Role comes from the database, not the
    token, so a role change or deactivation takes effect on the very next request."""
    try:
        user_id = decode_access_token(token, settings)
    except InvalidToken as exc:
        code = "token_expired" if str(exc) == "expired" else "token_invalid"
        raise Unauthenticated("Access token is invalid or expired", code=code) from exc
    user = await user_repo.get_user(session, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Account unavailable", code="account_disabled")
    return user


async def _issue(session: AsyncSession, settings: Settings, user: User) -> AuthSession:
    raw = new_refresh_token()
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        expires_at=refresh_expiry(settings),
    )
    session.add(token_row)
    await session.flush()
    return AuthSession(
        user=user,
        access=create_access_token(user.id, settings),
        refresh_token=raw,
        refresh_token_id=token_row.id,
    )


# ---------------------------------------------------------------- forgot / reset password

# One reset email per account per this long, however often someone asks.
RESET_COOLDOWN = timedelta(seconds=60)


async def forgot_password(session: AsyncSession, settings: Settings, *, email: str) -> None:
    """Email a single-use reset link. Always "succeeds" from the caller's point of view,
    so the endpoint cannot be used to discover which emails have accounts."""
    user = await user_repo.get_user_by_email(session, email)
    if user is None or not user.is_active:
        log.info("password_reset_requested", outcome="no_active_account")
        return
    now = utcnow()
    recent = await session.scalar(
        select(PasswordResetToken.id).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at > now - RESET_COOLDOWN,
        )
    )
    if recent is not None:
        log.info("password_reset_requested", outcome="cooldown", user_id=str(user.id))
        return

    raw = new_reset_token()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw),
            expires_at=now + timedelta(minutes=settings.password_reset_minutes),
        )
    )
    link = f"{settings.app_base_url.rstrip('/')}/reset-password?token={raw}"
    minutes = settings.password_reset_minutes
    message = render_message(
        subject="Reset your Tasky password",
        headline="Password reset",
        title="Choose a new password",
        intro="Someone (hopefully you) asked to reset the password for this account. "
        "Use the button below to choose a new one."
        if user.password_hash
        else "This account signs in with Google. Use the button below if you would also "
        "like a password.",
        cta="Choose a new password",
        url=link,
        recipient=user,
        when=now,
        note=f"The link works once and expires in {minutes} minutes. If you did not ask "
        "for this, ignore this email: your password stays the same.",
        footer="Tasky sends this because a password reset was requested.",
    )
    notify_user(session, user, NotificationKind.PASSWORD_RESET, message, in_app=False)
    await session.commit()
    log.info("password_reset_requested", outcome="sent", user_id=str(user.id))


async def reset_password(session: AsyncSession, *, token: str, password: str) -> User:
    """Use a reset link: set the password, burn every outstanding link for the account,
    and sign out every session (whoever had the old password loses access)."""
    invalid = InvalidInput(
        "This reset link is invalid or has expired. Ask for a new one.", code="reset_invalid"
    )
    now = utcnow()
    row = await session.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_reset_token(token))
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise invalid
    user = await user_repo.get_user(session, row.user_id)
    if user is None or not user.is_active:
        raise invalid

    user.password_hash = hash_password(password)
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    await user_repo.revoke_all_refresh_tokens(session, user.id, at=now)
    await session.commit()
    log.info("password_reset_completed", user_id=str(user.id))
    return user


async def finish_onboarding(session: AsyncSession, user: User) -> None:
    """The first-sign-in page was answered; it is not shown again (idempotent)."""
    if user.onboarded_at is None:
        user.onboarded_at = utcnow()
        await session.commit()
        log.info("user_onboarded", user_id=str(user.id))


# ---------------------------------------------------------------- Google


async def google_login(
    session: AsyncSession, settings: Settings, profile: GoogleProfile
) -> AuthSession:
    """Sign in with a Google profile: match by Google id, then by verified email (and
    link the two), else create an account when self-registration is open."""
    if not profile.email_verified:
        raise GoogleError("google_email_unverified")

    user = await session.scalar(select(User).where(User.google_sub == profile.sub))
    if user is None:
        user = await user_repo.get_user_by_email(session, profile.email)
        if user is not None:
            if user.google_sub not in (None, profile.sub):
                raise GoogleError("google_account_mismatch")
            user.google_sub = profile.sub
            log.info("google_account_linked", user_id=str(user.id))
    if user is None:
        if not settings.allow_self_register:
            raise GoogleError("registration_closed")
        user = User(
            name=profile.name,
            email=profile.email,
            password_hash=None,
            google_sub=profile.sub,
            avatar_color=avatar_color_for(profile.email),
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:  # a concurrent sign-up with the same email or sub
            await session.rollback()
            raise GoogleError("google_retry") from exc
        log.info("user_registered", user_id=str(user.id), via="google")
    if not user.is_active:
        raise GoogleError("account_disabled")

    result = await _issue(session, settings, user)
    await session.commit()
    log.info("login_succeeded", user_id=str(user.id), via="google")
    return result

"""/api/v1/auth -- HTTP only; every rule lives in services/auth_service.py.

The refresh token travels only in an HttpOnly, SameSite=Strict cookie scoped to
``/api/v1/auth``; JavaScript never sees it and it is never sent to other routes. The
access token is returned in the body and kept in memory by the SPA.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import Settings
from app.core.deps import AppSettings, CurrentUser, DbSession, OptionalUser
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.core.security import InvalidToken, read_state, sign_state
from app.db.session import get_sessionmaker
from app.schemas.user import (
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
)
from app.services import auth_service, google_oauth, supabase_auth

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
GOOGLE_COOKIE = "google_oauth"
GOOGLE_COOKIE_PATH = "/api/v1/auth/google"

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE, include_in_schema=False)]


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.use_secure_cookies,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.use_secure_cookies,
        samesite="strict",
    )


def _token_out(result: auth_service.AuthSession) -> TokenOut:
    return TokenOut(
        access_token=result.access.token,
        expires_in=result.access.expires_in,
        user=UserOut.model_validate(result.user),
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserOut,
    summary="Create an account",
    description="Public when ALLOW_SELF_REGISTER=true, otherwise admin only. "
    "New accounts get the member role.",
    dependencies=[Depends(rate_limit("register", lambda s: s.register_rate_limit_per_min))],
)
async def register(
    body: RegisterIn,
    session: DbSession,
    settings: AppSettings,
    actor: OptionalUser,
    background: BackgroundTasks,
) -> UserOut:
    user = await auth_service.register(
        session, settings, name=body.name, email=body.email, password=body.password, actor=actor
    )
    _copy_to_supabase_auth(background, settings)
    return UserOut.model_validate(user)


def _copy_to_supabase_auth(background: BackgroundTasks, settings: Settings) -> None:
    """After the response: copy new accounts into Supabase Auth (the worker retries)."""
    if settings.supabase_auth_copy_enabled:
        background.add_task(supabase_auth.copy_missing_now, get_sessionmaker(), settings)


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Sign in",
    description="Returns an access token and sets the rotating refresh-token cookie.",
    dependencies=[Depends(rate_limit("login", lambda s: s.login_rate_limit_per_min))],
)
async def login(
    body: LoginIn, response: Response, session: DbSession, settings: AppSettings
) -> TokenOut:
    result = await auth_service.login(session, settings, email=body.email, password=body.password)
    _set_refresh_cookie(response, result.refresh_token, settings)
    return _token_out(result)


@router.post(
    "/refresh",
    response_model=TokenOut,
    summary="Rotate the refresh token",
    description="Exchanges the refresh cookie for a new access token and a new cookie. "
    "Reusing a rotated token revokes every session of that user.",
)
async def refresh(
    response: Response, session: DbSession, settings: AppSettings, token: RefreshCookie = None
) -> TokenOut:
    try:
        result = await auth_service.refresh(session, settings, token=token)
    except AppError as exc:
        # A rejected cookie should not linger in the browser. The error handler builds
        # a fresh response, so the deletion has to travel on the error itself.
        cleared = Response()
        _clear_refresh_cookie(cleared, settings)
        exc.headers["set-cookie"] = cleared.headers["set-cookie"]
        raise
    _set_refresh_cookie(response, result.refresh_token, settings)
    return _token_out(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(
    session: DbSession, settings: AppSettings, token: RefreshCookie = None
) -> Response:
    await auth_service.logout(session, token=token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/me", response_model=UserOut, summary="Current user")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/me/onboarded",
    response_model=UserOut,
    summary="Finish first-sign-in onboarding",
    description="Marks the first-sign-in page as answered (created a team, or skipped).",
)
async def finish_onboarding(user: CurrentUser, session: DbSession) -> UserOut:
    await auth_service.finish_onboarding(session, user)
    return UserOut.model_validate(user)


class AuthConfig(BaseModel):
    """What the sign-in page may offer. Public: it is needed before anyone signs in."""

    allow_self_register: bool
    demo_mode: bool
    google_enabled: bool


@router.get("/config", response_model=AuthConfig, summary="Sign-in page options (public)")
async def auth_config(settings: AppSettings) -> AuthConfig:
    return AuthConfig(
        allow_self_register=settings.allow_self_register,
        demo_mode=settings.demo_mode,
        google_enabled=settings.google_enabled,
    )


# ---------------------------------------------------------------- forgot / reset password


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password-reset link",
    description="Always 202, whether or not the email has an account, so it cannot be "
    "used to find out who is registered. The link works once and expires after "
    "PASSWORD_RESET_MINUTES.",
    dependencies=[
        Depends(rate_limit("forgot_password", lambda s: s.forgot_password_rate_limit_per_min))
    ],
)
async def forgot_password(
    body: ForgotPasswordIn, session: DbSession, settings: AppSettings
) -> Response:
    await auth_service.forgot_password(session, settings, email=body.email)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with a reset link",
    description="Burns the link and signs the account out everywhere. 422 `reset_invalid` "
    "for an unknown, used or expired link.",
    dependencies=[
        Depends(rate_limit("reset_password", lambda s: s.forgot_password_rate_limit_per_min * 3))
    ],
)
async def reset_password(body: ResetPasswordIn, session: DbSession) -> Response:
    await auth_service.reset_password(session, token=body.token, password=body.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- Google


def _safe_next(value: str | None) -> str:
    """Only same-site paths: never an open redirect."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"


def _login_error(code: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?error={quote(code)}", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(GOOGLE_COOKIE, path=GOOGLE_COOKIE_PATH)
    return response


@router.get(
    "/google/start",
    summary="Start signing in with Google",
    description="Redirects to Google. 302 to /login?error=google_disabled when "
    "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set.",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def google_start(
    settings: AppSettings, next_: Annotated[str | None, Query(alias="next")] = None
) -> RedirectResponse:
    if not settings.google_enabled:
        return _login_error("google_disabled")
    state = secrets.token_urlsafe(24)
    pkce = google_oauth.new_pkce()
    response = RedirectResponse(
        google_oauth.authorize_url(settings, state=state, challenge=pkce.challenge),
        status_code=status.HTTP_302_FOUND,
    )
    # Lax, not Strict: it must come back on Google's top-level redirect to the callback.
    response.set_cookie(
        GOOGLE_COOKIE,
        sign_state(
            {"state": state, "verifier": pkce.verifier, "next": _safe_next(next_)}, settings
        ),
        max_age=600,
        path=GOOGLE_COOKIE_PATH,
        httponly=True,
        secure=settings.use_secure_cookies,
        samesite="lax",
    )
    return response


@router.get(
    "/google/callback",
    summary="Google redirects here",
    description="Checks state + PKCE, signs in (creating or linking the account), sets the "
    "refresh cookie and redirects into the app. Failures redirect to /login?error=<code>.",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def google_callback(
    session: DbSession,
    settings: AppSettings,
    background: BackgroundTasks,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    cookie: Annotated[str | None, Cookie(alias=GOOGLE_COOKIE, include_in_schema=False)] = None,
) -> RedirectResponse:
    if not settings.google_enabled:
        return _login_error("google_disabled")
    if error:
        return _login_error("google_cancelled" if error == "access_denied" else "google_failed")
    if not (code and state and cookie):
        return _login_error("google_expired")
    try:
        saved = read_state(cookie, settings)
    except InvalidToken:
        return _login_error("google_expired")
    if not hmac.compare_digest(saved.get("state", ""), state):
        log.warning("google_state_mismatch")
        return _login_error("google_expired")

    try:
        profile = await google_oauth.fetch_profile(
            settings, code=code, verifier=saved.get("verifier", "")
        )
        result = await auth_service.google_login(session, settings, profile)
    except google_oauth.GoogleError as exc:
        log.info("google_login_failed", code=exc.code)
        return _login_error(exc.code)

    _copy_to_supabase_auth(background, settings)  # a first Google sign-in creates an account
    response = RedirectResponse(_safe_next(saved.get("next")), status_code=status.HTTP_302_FOUND)
    response.delete_cookie(GOOGLE_COOKIE, path=GOOGLE_COOKIE_PATH)
    _set_refresh_cookie(response, result.refresh_token, settings)
    return response

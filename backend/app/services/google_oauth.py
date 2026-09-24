"""Sign in with Google: OAuth 2.0 authorization code flow with PKCE, no SDK.

1. ``authorize_url`` sends the browser to Google with a random ``state`` and a PKCE
   challenge (both also kept in a signed, HttpOnly cookie for the round trip).
2. Google redirects back to ``/api/v1/auth/google/callback`` with a one-time ``code``.
3. ``fetch_profile`` exchanges the code (plus the PKCE verifier and client secret) for an
   access token, server to server, and reads the OpenID userinfo.

Only an email Google has verified is trusted; the account is matched by Google's stable
``sub`` first, then by that verified email.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"


class GoogleError(Exception):
    """Google refused, or answered with something we cannot trust. ``code`` is safe to
    show to the user (it becomes ``/login?error=<code>``)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    email_verified: bool
    name: str


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


def new_pkce() -> Pkce:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return Pkce(verifier=verifier, challenge=challenge)


def authorize_url(settings: Settings, *, state: str, challenge: str) -> str:
    params = {
        "client_id": settings.google_client_id or "",
        "redirect_uri": settings.google_callback_url,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def fetch_profile(
    settings: Settings, *, code: str, verifier: str, client: httpx.AsyncClient | None = None
) -> GoogleProfile:
    own = client is None
    http = client or httpx.AsyncClient(timeout=15)
    try:
        token_res = await http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id or "",
                "client_secret": settings.google_client_secret or "",
                "redirect_uri": settings.google_callback_url,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        if token_res.status_code != 200:
            log.warning(
                "google_token_exchange_failed",
                status=token_res.status_code,
                body=token_res.text[:300],
            )
            raise GoogleError("google_exchange_failed")
        access_token = token_res.json().get("access_token")
        if not isinstance(access_token, str):
            raise GoogleError("google_exchange_failed", "no access_token")

        info_res = await http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if info_res.status_code != 200:
            log.warning("google_userinfo_failed", status=info_res.status_code)
            raise GoogleError("google_exchange_failed", "userinfo")
        info = info_res.json()
    except httpx.HTTPError as exc:
        log.warning("google_unreachable", error=type(exc).__name__)
        raise GoogleError("google_unreachable") from exc
    finally:
        if own:
            await http.aclose()

    sub, email = info.get("sub"), info.get("email")
    if not isinstance(sub, str) or not isinstance(email, str) or "@" not in email:
        raise GoogleError("google_exchange_failed", "profile without sub/email")
    name = info.get("name") or info.get("given_name") or email.split("@", 1)[0]
    return GoogleProfile(
        sub=sub,
        email=email.strip().lower(),
        email_verified=info.get("email_verified") is True,
        name=str(name).strip()[:100] or email.split("@", 1)[0],
    )

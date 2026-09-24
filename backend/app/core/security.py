"""Password hashing and token primitives. No HTTP, no database.

* Passwords: argon2id via pwdlib (OWASP's current recommendation, memory-hard).
* Access tokens: JWT HS256, 15 min, ``sub`` = user id, ``typ`` = "access".
* Refresh tokens: 256 random bits, opaque; only their SHA-256 is stored, so a leaked
  database cannot be replayed as sessions.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings
from app.db.base import utcnow

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - token type label, not a secret

_password_hash = PasswordHash((Argon2Hasher(),))
# Verified against when the email is unknown, so "no such user" and "wrong password"
# take the same time and cannot be told apart.
_DUMMY_HASH = _password_hash.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Return (valid, new_hash). ``new_hash`` is set when parameters were upgraded."""
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False, None
    return _password_hash.verify_and_update(password, password_hash)


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_in: int  # seconds


class InvalidToken(Exception):
    pass


def create_access_token(user_id: uuid.UUID, settings: Settings) -> AccessToken:
    now = utcnow()
    lifetime = timedelta(minutes=settings.access_token_minutes)
    claims = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + lifetime,
        "jti": secrets.token_hex(8),
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)
    return AccessToken(token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Return the user id, or raise :class:`InvalidToken` (expired, forged, wrong type)."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],  # never trust the token's own "alg"
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidToken("invalid") from exc
    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        raise InvalidToken("wrong_type")
    try:
        return uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise InvalidToken("invalid_subject") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_expiry(settings: Settings) -> datetime:
    return utcnow() + timedelta(days=settings.refresh_token_days)


# ---------------------------------------------------------------- short-lived signed state

OAUTH_STATE_TYPE = "oauth_state"


def sign_state(payload: dict[str, str], settings: Settings, *, minutes: int = 10) -> str:
    """A tamper-proof, expiring blob for the OAuth round trip (state, PKCE verifier)."""
    claims = {**payload, "typ": OAUTH_STATE_TYPE, "exp": utcnow() + timedelta(minutes=minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def read_state(token: str, settings: Settings) -> dict[str, str]:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidToken("invalid_state") from exc
    if claims.get("typ") != OAUTH_STATE_TYPE:
        raise InvalidToken("invalid_state")
    return {k: str(v) for k, v in claims.items() if k not in ("typ", "exp")}


def new_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

"""Profile photos: set (replacing the old one) and remove.

The browser crops and scales the photo to a small square before uploading; the server
still checks size and the real type (PNG, JPEG or GIF, sniffed from the bytes) and never
trusts a client header. Each upload gets a fresh random key, so a served photo can be
cached forever and replacing it needs no cache busting.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import User
from app.services.attachment_service import IMAGE_TYPES, UnsupportedType, sniff
from app.storage import LocalStorage, S3Storage, StorageError

log = get_logger(__name__)

MAX_AVATAR_BYTES = 2 * 1024 * 1024
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif"}
CONTENT_TYPES = {ext: ct for ct, ext in EXTENSIONS.items()}
# What /api/v1/avatars/{name} accepts: only keys this module made.
NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif)$")


def content_type_of(name: str) -> str:
    return CONTENT_TYPES[name.rsplit(".", 1)[1]]


async def _drop(storage: LocalStorage | S3Storage, key: str | None) -> None:
    if not key:
        return
    try:
        await storage.delete(key)
    except StorageError:  # an orphaned file is harmless; the account is already updated
        log.warning("avatar_delete_failed", key=key)


async def set_avatar(
    session: AsyncSession, storage: LocalStorage | S3Storage, user: User, data: bytes
) -> User:
    try:
        content_type = sniff("avatar", data)
    except UnsupportedType:
        content_type = ""
    if content_type not in IMAGE_TYPES:
        raise UnsupportedType("Use a PNG, JPEG or GIF image")
    key = f"avatars/{uuid.uuid4().hex}.{EXTENSIONS[content_type]}"
    await storage.put(key, data, content_type)
    old, user.avatar_key = user.avatar_key, key
    await session.commit()
    await _drop(storage, old)
    log.info("avatar_set", user_id=str(user.id), bytes=len(data))
    return user


async def remove_avatar(
    session: AsyncSession, storage: LocalStorage | S3Storage, user: User
) -> User:
    old, user.avatar_key = user.avatar_key, None
    await session.commit()
    await _drop(storage, old)
    log.info("avatar_removed", user_id=str(user.id))
    return user

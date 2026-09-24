"""Attachments: validate, store, list, sign downloads, delete (spec 13: allow-list,
10 MB, random key, presigned URL, never executed).

The client's Content-Type is ignored: the type is decided from the file's first bytes
(and, for text, from the extension plus a UTF-8 check), so a renamed executable or an
HTML page posing as an image is refused.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, InvalidInput, NotFound, PermissionDenied
from app.core.logging import get_logger
from app.models import Attachment, Comment, EventType, User
from app.models.incident import key_for
from app.services import incident_service
from app.services import permissions as perms
from app.storage import LocalStorage, S3Storage, StorageError, new_key

log = get_logger(__name__)

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif"}
TEXT_EXTENSIONS = {".txt": "text/plain", ".log": "text/plain", ".json": "application/json"}
ALLOWED = "PNG, JPEG, GIF, PDF, TXT, LOG, JSON"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"


class UnsupportedType(AppError):
    status_code = 415
    code = "unsupported_type"


def sniff(filename: str, data: bytes) -> str:
    """The real content type, or UnsupportedType."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    ext = PurePath(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        if b"\x00" in data:
            raise UnsupportedType("Binary data is not a text file")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedType("Text files must be UTF-8") from exc
        if ext == ".json":
            try:
                json.loads(text)
            except ValueError as exc:
                raise UnsupportedType("This .json file is not valid JSON") from exc
        return TEXT_EXTENSIONS[ext]
    raise UnsupportedType(
        f"This file type is not allowed. Allowed: {ALLOWED}", details={"allowed": ALLOWED}
    )


_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")


def clean_filename(raw: str) -> str:
    """Display name only (storage never uses it): no paths, no control characters."""
    name = PurePath(raw.replace("\\", "/")).name
    name = _UNSAFE.sub("_", name).strip(" .")
    return (name or "file")[:200]


async def upload(
    session: AsyncSession,
    storage: LocalStorage | S3Storage,
    actor: User,
    raw_ident: str,
    *,
    filename: str,
    data: bytes,
    max_bytes: int,
    comment_id: uuid.UUID | None = None,
) -> Attachment:
    incident = await incident_service.load_live(
        session, incident_service.parse_ident(raw_ident), actor
    )
    if not perms.can_comment(actor):
        raise PermissionDenied("Viewers cannot add attachments")
    if not data:
        raise InvalidInput("The file is empty", code="empty_file")
    if len(data) > max_bytes:
        raise PayloadTooLarge(f"Files can be at most {max_bytes // (1024 * 1024)} MB")
    if comment_id is not None:
        comment = await session.get(Comment, comment_id)
        if comment is None or comment.incident_id != incident.id:
            raise InvalidInput("That comment is not on this task", code="invalid_comment")

    name = clean_filename(filename)
    content_type = sniff(name, data)
    key = new_key(str(incident.id))
    try:
        await storage.put(key, data, content_type)
    except StorageError as exc:
        log.error("attachment_store_failed", error=str(exc))
        raise AppError("Could not store the file, try again", code="storage_error") from exc

    attachment = Attachment(
        incident_id=incident.id,
        comment_id=comment_id,
        uploader_id=actor.id,
        filename=name,
        content_type=content_type,
        size_bytes=len(data),
        storage_key=key,
    )
    session.add(attachment)
    await session.flush()
    incident_service.record_event(
        session,
        incident,
        actor,
        EventType.ATTACHMENT_ADDED,
        field="attachment",
        new={"id": str(attachment.id), "filename": name, "size_bytes": len(data)},
    )
    try:
        await session.commit()
    except Exception:
        await storage.delete(key)  # no row, no orphaned bytes
        raise
    log.info("attachment_added", incident=key_for(incident.number), bytes=len(data))
    return await _get(session, attachment.id)


async def list_for(session: AsyncSession, actor: User, raw_ident: str) -> Sequence[Attachment]:
    incident = await incident_service.load(session, incident_service.parse_ident(raw_ident), actor)
    rows = await session.scalars(
        select(Attachment)
        .where(Attachment.incident_id == incident.id)
        .order_by(Attachment.created_at.desc(), Attachment.id)
    )
    return rows.all()


async def _get(session: AsyncSession, attachment_id: uuid.UUID) -> Attachment:
    attachment = await session.get(Attachment, attachment_id, populate_existing=True)
    if attachment is None:
        raise NotFound("Attachment not found")
    return attachment


async def get_visible(session: AsyncSession, actor: User, attachment_id: uuid.UUID) -> Attachment:
    attachment = await _get(session, attachment_id)
    await incident_service.load(session, attachment.incident_id, actor)  # 404 if not visible
    return attachment


async def delete(
    session: AsyncSession, storage: LocalStorage | S3Storage, actor: User, attachment_id: uuid.UUID
) -> None:
    attachment = await get_visible(session, actor, attachment_id)
    if not (perms.is_admin(actor) or attachment.uploader_id == actor.id):
        raise PermissionDenied("Only the uploader or an admin can remove an attachment")
    incident = await incident_service.load_live(session, attachment.incident_id, actor)
    key = attachment.storage_key
    incident_service.record_event(
        session,
        incident,
        actor,
        EventType.ATTACHMENT_DELETED,
        field="attachment",
        old={"id": str(attachment.id), "filename": attachment.filename},
    )
    await session.delete(attachment)
    await session.commit()
    try:
        await storage.delete(key)
    except StorageError as exc:  # the row is gone; a stray object is harmless and logged
        log.warning("attachment_blob_delete_failed", key=key, error=str(exc))

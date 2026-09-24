"""Attachments: upload to an incident, list, download via a short-lived link, delete.

Uploads send the raw file as the request body (``Content-Type`` is ignored; the server
sniffs the real type) with the name in ``?filename=``. That keeps the API free of a
multipart parser and lets the size limit stop a large body while it is still arriving.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.deps import AppSettings, DbSession, TeamUser
from app.core.errors import NotFound, PermissionDenied
from app.models import Attachment, User
from app.schemas.attachment import AttachmentOut, DownloadLink
from app.schemas.user import UserPublic
from app.services import attachment_service
from app.services import permissions as perms
from app.services.attachment_service import IMAGE_TYPES, PayloadTooLarge
from app.storage import LocalStorage, S3Storage

router = APIRouter(prefix="/api/v1", tags=["attachments"])


def _storage(request: Request) -> LocalStorage | S3Storage:
    storage: LocalStorage | S3Storage = request.app.state.storage
    return storage


def _out(a: Attachment, actor: User) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        incident_id=a.incident_id,
        comment_id=a.comment_id,
        filename=a.filename,
        content_type=a.content_type,
        size_bytes=a.size_bytes,
        is_image=a.content_type in IMAGE_TYPES,
        uploader=UserPublic.model_validate(a.uploader),
        created_at=a.created_at,
        can_delete=perms.is_admin(actor) or a.uploader_id == actor.id,
    )


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(f"Files can be at most {limit // (1024 * 1024)} MB")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge(f"Files can be at most {limit // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/incidents/{ident}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an attachment",
    description="Body: the raw file. Allowed: PNG, JPEG, GIF, PDF, TXT, LOG, JSON; "
    "at most MAX_UPLOAD_MB. The type is detected from the content, not the header.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    ident: str,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    actor: TeamUser,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    comment_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AttachmentOut:
    if not perms.can_comment(actor):  # refuse before reading a byte
        raise PermissionDenied("Viewers cannot add attachments")
    limit = settings.max_upload_mb * 1024 * 1024
    data = await _read_body(request, limit)
    attachment = await attachment_service.upload(
        session,
        _storage(request),
        actor,
        ident,
        filename=filename,
        data=data,
        max_bytes=limit,
        comment_id=comment_id,
    )
    return _out(attachment, actor)


@router.get(
    "/incidents/{ident}/attachments",
    response_model=list[AttachmentOut],
    summary="List attachments",
)
async def list_attachments(ident: str, session: DbSession, actor: TeamUser) -> list[AttachmentOut]:
    return [_out(a, actor) for a in await attachment_service.list_for(session, actor, ident)]


@router.get(
    "/attachments/{attachment_id}/download",
    summary="Download (302 to a short-lived link)",
    description="Redirects to a presigned URL. Send `Accept: application/json` to get the "
    "link as JSON instead (for <img> previews, which cannot send a bearer token).",
    responses={302: {"description": "Redirect to the file"}, 200: {"model": DownloadLink}},
    response_model=None,
)
async def download(
    attachment_id: uuid.UUID,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    actor: TeamUser,
    inline: bool = False,
) -> RedirectResponse | DownloadLink:
    attachment = await attachment_service.get_visible(session, actor, attachment_id)
    url = _storage(request).download_url(
        attachment.storage_key,
        filename=attachment.filename,
        content_type=attachment.content_type,
        # Only images render inline; PDFs and text always download.
        inline=inline and attachment.content_type in IMAGE_TYPES,
    )
    if "application/json" in request.headers.get("accept", ""):
        return DownloadLink(url=url, expires_in=settings.download_url_seconds)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an attachment (uploader or admin)",
)
async def delete(
    attachment_id: uuid.UUID, request: Request, session: DbSession, actor: TeamUser
) -> Response:
    await attachment_service.delete(session, _storage(request), actor, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/files",
    summary="Serve a locally stored file (signed link)",
    include_in_schema=False,
)
async def serve_local(
    request: Request,
    key: str,
    exp: int,
    cd: str,
    ct: str,
    sig: str,
) -> Response:
    storage = _storage(request)
    if not isinstance(storage, LocalStorage) or not storage.verify(key, exp, cd, ct, sig):
        raise NotFound("Link expired or invalid")
    try:
        data = storage.read(key)
    except (OSError, ValueError) as exc:
        raise NotFound("File not found") from exc
    return Response(
        content=data,
        media_type=ct,
        headers={
            "Content-Disposition": cd,
            "X-Content-Type-Options": "nosniff",
            # Never executed: no scripts, no plugins, no same-origin powers.
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
            "Cache-Control": "private, max-age=300",
        },
    )

"""/api/v1/comments/{id} -- edit or delete a single comment."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.core.deps import DbSession, TeamUser
from app.db.base import utcnow
from app.schemas.incident import CommentOut, CommentUpdate
from app.services import comment_service, presenters

router = APIRouter(prefix="/api/v1/comments", tags=["comments"])


@router.patch(
    "/{comment_id}",
    response_model=CommentOut,
    summary="Edit a comment",
    description="Own comments within 15 minutes of posting; admins any time.",
)
async def edit_comment(
    comment_id: uuid.UUID, body: CommentUpdate, session: DbSession, actor: TeamUser
) -> CommentOut:
    comment = await comment_service.edit(session, actor, comment_id, body=body.body)
    return presenters.comment_out(comment, actor, utcnow())


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a comment")
async def delete_comment(comment_id: uuid.UUID, session: DbSession, actor: TeamUser) -> Response:
    await comment_service.delete(session, actor, comment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

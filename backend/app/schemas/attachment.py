from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.user import UserPublic


class AttachmentOut(BaseModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    comment_id: uuid.UUID | None
    filename: str
    content_type: str
    size_bytes: int
    is_image: bool
    uploader: UserPublic
    created_at: datetime
    can_delete: bool


class DownloadLink(BaseModel):
    url: str
    expires_in: int

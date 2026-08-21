from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class MessageBase(BaseModel):
    channel_discord_id: str
    content: str
    message_type: str
    # Present only on model messages produced by a reasoning model.
    reasoning_details: list[dict[str, Any]] | None = None

class MessageCreate(MessageBase):
    user_id: UUID
    session_id: UUID
    conversation_id: UUID

class MessageSchema(MessageBase):
    id: UUID
    timestamp: datetime
    user_id: UUID
    session_id: UUID
    conversation_id: UUID

    class Config:
        from_attributes = True

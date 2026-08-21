from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class MessageBase(BaseModel):
    channel_discord_id: str
    content: str
    message_type: str

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
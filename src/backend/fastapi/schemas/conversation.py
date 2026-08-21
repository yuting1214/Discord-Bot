from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ConversationBase(BaseModel):
    pass

class ConversationCreate(ConversationBase):
    session_id: UUID

class ConversationUpdate(ConversationBase):
    end_time: datetime

class ConversationSchema(ConversationBase):
    id: UUID
    session_id: UUID
    start_time: datetime
    end_time: datetime | None = None

    class Config:
        from_attributes = True
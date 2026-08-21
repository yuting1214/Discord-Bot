from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

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
    end_time: Optional[datetime] = None

    class Config:
        from_attributes = True
from typing import Optional, List
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class SessionBase(BaseModel):
    channel_discord_id: str
    is_active: bool
    is_group: bool

class SessionCreate(SessionBase):
    users: List[UUID] = []  # List of user IDs to associate with the session

class SessionUpdate(BaseModel):
    is_active: bool
    end_time: Optional[datetime]

class SessionSchema(SessionBase):
    id: UUID
    start_time: datetime
    end_time: Optional[datetime] = None

    class Config:
        from_attributes = True

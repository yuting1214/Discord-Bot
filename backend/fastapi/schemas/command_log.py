from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CommandLogBase(BaseModel):
    pass

class CommandLogCreate(CommandLogBase):
    user_id: UUID
    session_id: UUID
    command_id: UUID

class CommandLogUpdate(CommandLogBase):
    user_id: UUID
    session_id: UUID
    command_id: UUID

class CommandLogSchema(CommandLogBase):
    id: UUID
    timestamp: datetime
    user_id: UUID
    session_id: UUID
    command_id: UUID

    class Config:
        from_attributes = True
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SessionBase(BaseModel):
    channel_discord_id: str
    is_active: bool
    is_group: bool

class SessionCreate(SessionBase):
    users: list[UUID] = []  # List of user IDs to associate with the session

class SessionUpdate(BaseModel):
    is_active: bool
    end_time: datetime | None

class SessionSchema(SessionBase):
    id: UUID
    start_time: datetime
    end_time: datetime | None = None
    summary: str | None = None
    summarized_at: datetime | None = None

    class Config:
        from_attributes = True


class SessionSummary(BaseModel):
    """The result of summarising one session.

    ``summary`` is null when there was nothing worth summarising -- a session of
    one message, or none.
    """

    session_id: UUID
    summary: str | None = None
    summarized: bool

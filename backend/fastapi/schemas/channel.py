from pydantic import BaseModel, Field
from uuid import UUID
from typing import List, Optional

class ChannelBase(BaseModel):
    channel_discord_id: str = Field(..., description="The Discord ID of the channel")
    channel_name: Optional[str] = Field(None, description="The name of the channel")
    server_id: UUID = Field(..., description="The server ID the channel belongs to")
    user_id: Optional[UUID] = Field(None, description="The user ID of the channel")
    is_group: bool = Field(..., description="Indicates if the channel is a group channel")

class ChannelCreate(ChannelBase):
    users: List[UUID] = Field(default=[], description="List of user IDs for the channel")

class ChannelUpdate(BaseModel):
    channel_discord_id: Optional[str] = Field(None, description="The Discord ID of the channel")
    channel_name: Optional[str] = Field(None, description="The name of the channel")

class ChannelSchema(ChannelBase):
    id: UUID = Field(..., description="The unique ID of the channel")

    class Config:
        from_attributes = True

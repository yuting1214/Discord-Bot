from pydantic import BaseModel
from uuid import UUID
from typing import List

class ServerBase(BaseModel):
    server_discord_id: str
    server_name: str
    owner_discord_id: str

class ServerCreate(ServerBase):
    users: List[UUID] = [] 

class ServerSchema(ServerBase):
    id: UUID

    class Config:
        from_attributes = True

from uuid import UUID

from pydantic import BaseModel


class ServerBase(BaseModel):
    server_discord_id: str
    server_name: str
    owner_discord_id: str

class ServerCreate(ServerBase):
    users: list[UUID] = [] 

class ServerSchema(ServerBase):
    id: UUID

    class Config:
        from_attributes = True

from uuid import UUID

from pydantic import BaseModel


class UserBase(BaseModel):
    discord_id: str
    username: str

class UserCreate(UserBase):
    pass

class UserSchema(UserBase):
    id: UUID

    class Config:
        from_attributes = True
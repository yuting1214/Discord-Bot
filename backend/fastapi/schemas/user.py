from pydantic import BaseModel
from uuid import UUID

class UserBase(BaseModel):
    discord_id: str
    username: str

class UserCreate(UserBase):
    pass

class UserSchema(UserBase):
    id: UUID

    class Config:
        from_attributes = True
from uuid import UUID

from pydantic import BaseModel


class CommandBase(BaseModel):
    name: str
    description: str

class CommandCreate(CommandBase):
    pass

class CommandSchema(CommandBase):
    id: UUID

    class Config:
        from_attributes = True
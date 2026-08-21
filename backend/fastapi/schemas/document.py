from uuid import UUID

from pydantic import BaseModel


class DocumentSchema(BaseModel):
    conversation_id: UUID
    session_id: UUID
    user_input: str
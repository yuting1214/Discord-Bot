from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class DocumentSchema(BaseModel):
    conversation_id: UUID
    session_id: UUID
    user_input: str
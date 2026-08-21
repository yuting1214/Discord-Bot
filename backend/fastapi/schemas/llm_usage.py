from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class LLMUsageBase(BaseModel):
    input_tokens: int
    output_tokens: int

class LLMUsageCreate(LLMUsageBase):
    llm_id: UUID
    session_id: UUID
    timestamp: datetime

class LLMUsageUpdate(LLMUsageCreate):
    pass

class LLMUsageSchema(LLMUsageBase):
    id: UUID
    llm_id: UUID
    session_id: UUID
    timestamp: datetime

    class Config:
        from_attributes = True
import uuid
from sqlalchemy import Column, ForeignKey, DateTime, Integer
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from backend.fastapi.dependencies.database import Base
from sqlalchemy.orm import relationship

class LLMUsage(Base):
    __tablename__ = "llm_usages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    llm_id = Column(UUID(as_uuid=True), ForeignKey('llms.id'))
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id'))
    timestamp = Column(DateTime, nullable=False, default=func.now())
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)

    # Relationships
    llm = relationship("LLM", back_populates="llm_usages")
    session = relationship("Session", back_populates="llm_usages")

    def __repr__(self):
        return f"<LLMUsage(id={self.id}, llm_id={self.llm_id}, session_id={self.session_id}, timestamp={self.timestamp}, input_tokens={self.input_tokens}, output_tokens={self.output_tokens})>"

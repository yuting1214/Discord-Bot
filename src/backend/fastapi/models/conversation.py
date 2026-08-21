import uuid

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.backend.fastapi.dependencies.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id'))
    start_time = Column(DateTime, nullable=False, default=func.now())
    end_time = Column(DateTime, nullable=True)

    # Relationships
    session = relationship("Session", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation")

    def __repr__(self):
        return f"<Conversation(id={self.id}, session_id={self.session_id}, start_time={self.start_time}, end_time={self.end_time})>"

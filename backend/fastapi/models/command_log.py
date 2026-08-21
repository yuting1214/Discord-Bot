import uuid
from sqlalchemy import Column, Text, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from backend.fastapi.dependencies.database import Base

class CommandLog(Base):
    __tablename__ = "command_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id'))
    command_id = Column(UUID(as_uuid=True), ForeignKey('commands.id'))
    timestamp = Column(DateTime, nullable=False, default=func.now())

    # Relationships
    user = relationship("User", back_populates="command_logs")
    session = relationship("Session", back_populates="command_logs")
    command = relationship("Command", back_populates="command_logs")

    def __repr__(self):
        return f"<CommandLog(id={self.id}, user_id={self.user_id}, session_id={self.session_id}, command_id={self.command_id}, timestamp={self.timestamp})>"

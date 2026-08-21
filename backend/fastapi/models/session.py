import uuid
from sqlalchemy import Column, DateTime, String, Boolean, Table, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from backend.fastapi.dependencies.database import Base

user_session_association_table = Table(
    "user_session_association",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("session_id", UUID(as_uuid=True), ForeignKey("sessions.id"), primary_key=True)
)

class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_discord_id = Column(String, nullable=False)
    start_time =  Column(DateTime, nullable=False, default=func.now())
    end_time = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False)
    is_group = Column(Boolean, nullable=False)

    # Relationships
    users = relationship("User", secondary=user_session_association_table, back_populates="sessions")
    messages = relationship("Message", back_populates="session")
    command_logs = relationship("CommandLog", back_populates="session")
    llm_usages = relationship("LLMUsage", back_populates="session")
    conversations = relationship("Conversation", back_populates="session")

    def __repr__(self):
        return f"<Session(id={self.id}, channel_discord_id={self.channel_discord_id}, start_time={self.start_time}, is_active={self.is_active}, is_group={self.is_group})>"

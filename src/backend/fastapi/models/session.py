import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.backend.fastapi.dependencies.database import Base
from src.backend.fastapi.models.search_document import Embedding

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

    # One embedding per session instead of one per turn. A session's summary is
    # dense and topical, where an individual turn is often "you good?" -- which
    # embeds to something plausible-looking and outranks genuinely relevant
    # turns. Written once when the session ends; see search/summary.py.
    summary = Column(Text, nullable=True)
    summary_vector = Column(Embedding, nullable=True)
    summarized_at = Column(DateTime, nullable=True)

    # Relationships
    users = relationship("User", secondary=user_session_association_table, back_populates="sessions")
    messages = relationship("Message", back_populates="session")
    command_logs = relationship("CommandLog", back_populates="session")
    llm_usages = relationship("LLMUsage", back_populates="session")
    conversations = relationship("Conversation", back_populates="session")

    def __repr__(self):
        return f"<Session(id={self.id}, channel_discord_id={self.channel_discord_id}, start_time={self.start_time}, is_active={self.is_active}, is_group={self.is_group})>"

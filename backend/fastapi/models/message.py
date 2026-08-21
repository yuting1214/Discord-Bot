import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.fastapi.dependencies.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id'))
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('conversations.id'))
    channel_discord_id = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    content = Column(Text, nullable=False)
    message_type = Column(ENUM('user', 'model', name='message_type'), nullable=False)
    # Reasoning trace returned with a model message. Replayed verbatim on the
    # next turn so a reasoning model continues rather than restarts. Null for
    # user messages and for non-reasoning models.
    reasoning_details = Column(JSON, nullable=True)

    # Relationships
    user = relationship("User", back_populates="messages")
    session = relationship("Session", back_populates="messages")
    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        return (
            f"<Message(id={self.id}, user_id={self.user_id}, session_id={self.session_id}, "
            f"conversation_id={self.conversation_id}, content={self.content}, "
            f"message_type={self.message_type}, timestamp={self.timestamp})>"
        )
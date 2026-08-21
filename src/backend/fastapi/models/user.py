import uuid

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.backend.fastapi.dependencies.database import Base
from src.backend.fastapi.models.channel import channel_user_association
from src.backend.fastapi.models.server import server_user_association
from src.backend.fastapi.models.session import user_session_association_table


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    discord_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=False)

    # Relationships
    messages = relationship("Message", back_populates="user")
    sessions = relationship("Session", secondary=user_session_association_table, back_populates="users")
    servers = relationship("Server", secondary=server_user_association, back_populates="users")
    channels = relationship("Channel", secondary=channel_user_association, back_populates="users")
    joined_channels = relationship("Channel", back_populates="joiner", foreign_keys="Channel.user_id")
    command_logs = relationship("CommandLog", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, discord_id={self.discord_id}, username={self.username})>"


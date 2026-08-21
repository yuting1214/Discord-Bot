import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.fastapi.dependencies.database import Base

# Association table for many-to-many relationship between Channel and User
channel_user_association = Table(
    'channel_user_association', Base.metadata,
    Column('channel_id', UUID(as_uuid=True), ForeignKey('channels.id'), primary_key=True),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), primary_key=True)
)

class Channel(Base):
    __tablename__ = "channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(UUID(as_uuid=True), ForeignKey('servers.id'), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)  # Only for non-group channels
    channel_discord_id = Column(String, nullable=False)
    channel_name = Column(String, nullable=True)    
    is_group = Column(Boolean, nullable=False)

    # Relationships
    server = relationship("Server", back_populates="channels")
    users = relationship("User", secondary=channel_user_association, back_populates="channels")
    joiner = relationship("User", back_populates="joined_channels", foreign_keys=[user_id])

    def __repr__(self):
        return f"<Channel(id={self.id}, channel_discord_id={self.channel_discord_id}, name={self.channel_name})>"

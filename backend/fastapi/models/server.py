import uuid

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.fastapi.dependencies.database import Base

# Association table for many-to-many relationship between Server and User
server_user_association = Table(
    'server_user_association', Base.metadata,
    Column('server_id', UUID(as_uuid=True), ForeignKey('servers.id'), primary_key=True),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), primary_key=True)
)

class Server(Base):
    __tablename__ = "servers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_discord_id = Column(String, unique=True, nullable=False)
    server_name = Column(String, unique=False, nullable=True)
    owner_discord_id = Column(String, unique=False, nullable=False)

    # Relationships
    channels = relationship("Channel", back_populates="server")
    users = relationship("User", secondary=server_user_association, back_populates="servers")

    def __repr(self):
        return f"<Server(id={self.id}, server_discord_id={self.server_discord_id}, server_name={self.server_name}, owner_discord_id={self.owner_discord_id})>"

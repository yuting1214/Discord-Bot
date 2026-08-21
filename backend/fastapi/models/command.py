import uuid
from sqlalchemy import Column, Text, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from backend.fastapi.dependencies.database import Base

class Command(Base):
    __tablename__ = "commands"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=False)

    # Relationships
    command_logs = relationship("CommandLog", back_populates="command")

    def __repr__(self):
        return f"<Command(id={self.id}, name={self.name}, description={self.description})>"

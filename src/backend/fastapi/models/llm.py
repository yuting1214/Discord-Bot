import uuid

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.backend.fastapi.dependencies.database import Base


class LLM(Base):
    __tablename__ = "llms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    llm_model_name = Column(String, unique=True, nullable=False)
    llm_vendor = Column(String, nullable=False)
    api_provider = Column(String, nullable=False)
    api_endpoint = Column(String, nullable=False)

    # Relationships
    llm_usages = relationship("LLMUsage", back_populates="llm")

    def __repr__(self):
        return f"<LLM(id={self.id}, name={self.llm_model_name}, vendor={self.llm_vendor}, api_provider={self.api_provider})>"
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.types import JSON, TypeDecorator

from src.backend.fastapi.dependencies.database import Base
from src.backend.search.embeddings import EMBEDDING_DIM


class Embedding(TypeDecorator):
    """pgvector's ``vector`` on PostgreSQL, JSON everywhere else.

    Keeps the development and test databases (SQLite) usable without pgvector,
    while production gets a real indexable vector column.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(JSON())


class SearchDocument(Base):
    """One searchable user message.

    Replaces the per-channel Meilisearch index. ``index_key`` is the channel id
    for group sessions and a hash of (user, channel) for single sessions, so one
    user's history is never searchable from another's.
    """

    __tablename__ = "search_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_key = Column(String, nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey('conversations.id'), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey('sessions.id'), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Embedding, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("ix_search_documents_index_key", "index_key"),
    )

    def __repr__(self):
        return f"<SearchDocument(id={self.id}, index_key={self.index_key})>"

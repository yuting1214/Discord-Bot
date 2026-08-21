"""Hybrid semantic + keyword search over stored messages.

Replaces Meilisearch, which cost a second always-on container, a volume and a
public service domain -- and which the bot reached over the public internet on
every message. The Railway PostgreSQL image already ships pgvector, so this runs
inside the database the template already deploys.

Scoring mirrors the previous behaviour: a weighted blend of semantic similarity
and keyword relevance, controlled by ``semantic_ratio``.
"""

import logging
import math

from sqlalchemy import Float, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.fastapi.models import SearchDocument
from src.backend.search.embeddings import embed

logger = logging.getLogger(__name__)

DEFAULT_SEMANTIC_RATIO = 0.5
DEFAULT_TOP_N = 3


async def index_document(
    db: AsyncSession,
    *,
    index_key: str,
    conversation_id,
    session_id,
    content: str,
    embedding: list[float] | None = None,
) -> SearchDocument:
    """Store a message so it can be searched later.

    ``embedding`` is accepted precomputed so callers can make the provider call
    outside their transaction rather than holding a connection across it.
    """
    if embedding is None:
        embedding = await embed(content)
    document = SearchDocument(
        index_key=index_key,
        conversation_id=conversation_id,
        session_id=session_id,
        content=content,
        embedding=embedding,
    )
    db.add(document)
    await db.flush()
    return document


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _keyword_score(content: str, query: str) -> float:
    """Fraction of query terms present, for backends without full-text ranking."""
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return 0.0
    content_lower = content.lower()
    return sum(1 for t in terms if t in content_lower) / len(terms)


async def _search_postgres(
    db: AsyncSession, index_key: str, query: str, embedding, semantic_ratio: float, top_n: int
) -> list[dict]:
    keyword = func.ts_rank(
        func.to_tsvector("english", SearchDocument.content),
        func.plainto_tsquery("english", query),
    )

    if embedding is None:
        score = keyword
    else:
        from pgvector.sqlalchemy import Vector

        from src.backend.search.embeddings import EMBEDDING_DIM

        # `<=>` is pgvector's cosine distance; similarity is 1 - distance.
        # The operator is applied explicitly rather than through
        # Vector.cosine_distance: the column is a TypeDecorator, which does not
        # inherit the wrapped type's comparator methods. The bind parameter is
        # given the Vector type directly so it is sent as a vector literal
        # rather than serialised as JSON.
        query_vector = literal(embedding, Vector(EMBEDDING_DIM))
        distance = SearchDocument.embedding.op("<=>", return_type=Float)(query_vector)
        score = semantic_ratio * (1 - distance) + (1 - semantic_ratio) * keyword

    rows = (
        await db.execute(
            select(SearchDocument.conversation_id, score.label("score"))
            .where(SearchDocument.index_key == index_key)
            .order_by(score.desc())
            .limit(top_n)
        )
    ).all()
    return [{"conversation_id": r.conversation_id, "score": float(r.score or 0.0)} for r in rows]


async def _search_python(
    db: AsyncSession, index_key: str, query: str, embedding, semantic_ratio: float, top_n: int
) -> list[dict]:
    """Fallback ranking for SQLite (development and tests)."""
    documents = (
        await db.execute(select(SearchDocument).where(SearchDocument.index_key == index_key))
    ).scalars().all()

    scored = []
    for document in documents:
        keyword = _keyword_score(document.content, query)
        if embedding is None or not document.embedding:
            score = keyword
        else:
            semantic = _cosine_similarity(embedding, document.embedding)
            score = semantic_ratio * semantic + (1 - semantic_ratio) * keyword
        scored.append({"conversation_id": document.conversation_id, "score": score})

    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_n]


async def hybrid_search(
    db: AsyncSession,
    index_key: str,
    query: str,
    semantic_ratio: float = DEFAULT_SEMANTIC_RATIO,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """Return ``top_n`` matching conversations, best first.

    Falls back to keyword-only scoring when an embedding is unavailable, so a
    provider outage degrades search rather than breaking it.
    """
    embedding = await embed(query)
    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
    search = _search_postgres if dialect == "postgresql" else _search_python
    results = await search(db, index_key, query, embedding, semantic_ratio, top_n)
    return [r for r in results if r["score"] > 0]


def to_conversation_ids_and_scores(results: list[dict]) -> tuple[list, list[float]]:
    return (
        [r["conversation_id"] for r in results],
        [round(r["score"], 3) for r in results],
    )

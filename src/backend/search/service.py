"""Hybrid lexical + semantic search over stored messages.

Replaces Meilisearch, which cost a second always-on container, a volume and a
public service domain -- and which the bot reached over the public internet on
every message. Both tiers now run inside the database the template deploys.

Two rankings are fused, because they fail in opposite directions. Measured on
real data: a content-free turn ("you good?") scored 0.0323 on vector similarity
and outranked a genuinely relevant one at 0.0046, while BM25 scores that same
filler at exactly 0.0000 and finds the relevant turn on an exact term.

They are combined with Reciprocal Rank Fusion rather than a weighted sum of
scores. The previous linear blend was unworkable: cosine similarity lands around
0.3-0.5 while ts_rank lands around 0.05, so a nominal 50/50 split behaved as
roughly 90% semantic. RRF combines *ranks*, which have no scale to mismatch.
"""

import logging
import math
import os

from sqlalchemy import Float, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.fastapi.models import SearchDocument
from src.backend.search.embeddings import embed

logger = logging.getLogger(__name__)

DEFAULT_SEMANTIC_RATIO = float(os.getenv("SEARCH_SEMANTIC_RATIO", "0.5"))
DEFAULT_TOP_N = int(os.getenv("SEARCH_TOP_N", "5"))

# Reciprocal Rank Fusion: score = weight / (RRF_K + rank). K damps the influence
# of the very top ranks so a single tier cannot dominate; 60 is the value from
# the original RRF paper and the de facto default.
RRF_K = int(os.getenv("SEARCH_RRF_K", "60"))
LEXICAL_WEIGHT = float(os.getenv("SEARCH_LEXICAL_WEIGHT", "1.0"))
SEMANTIC_WEIGHT = float(os.getenv("SEARCH_SEMANTIC_WEIGHT", "1.0"))

# Fusing ranks needs more candidates per tier than are finally shown.
CANDIDATE_MULTIPLIER = 4


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


def _fuse(rankings: list[tuple[float, list]]) -> list[dict]:
    """Reciprocal Rank Fusion over any number of ranked candidate lists.

    Each ranking is (weight, [conversation_id, ...]) in descending relevance.
    A document's score is the sum of weight / (RRF_K + rank) across the rankings
    it appears in, so agreeing tiers reinforce and neither can dominate on scale.
    """
    scores: dict = {}
    for weight, ordered in rankings:
        for rank, conversation_id in enumerate(ordered, start=1):
            scores[conversation_id] = scores.get(conversation_id, 0.0) + weight / (RRF_K + rank)
    fused = [{"conversation_id": cid, "score": score} for cid, score in scores.items()]
    fused.sort(key=lambda d: d["score"], reverse=True)
    return fused


async def _lexical_postgres(db: AsyncSession, index_key: str, query: str, limit: int) -> list:
    """BM25 ranking. Returns [] when the analyzer is absent, so a database
    without analyzer.sql applied degrades to semantic-only rather than erroring."""
    # Inside a SAVEPOINT: if BM25 is unavailable the statement fails, and a
    # failed statement aborts the whole transaction -- which would then take the
    # semantic tier down with it, turning graceful degradation into an outage.
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                text(
                    "SELECT conversation_id FROM search_documents "
                    "WHERE index_key = :key AND bm25 IS NOT NULL "
                    "ORDER BY bm25 <&> bm25_catalog.to_bm25query("
                    "  'search_documents_bm25_idx', public.to_bm25_query(:q)) "
                    "LIMIT :n"
                ),
                {"key": index_key, "q": query, "n": limit},
            )).scalars().all()
        return list(rows)
    except Exception:
        logger.warning("BM25 ranking unavailable; using semantic only", exc_info=True)
        return []


async def _semantic_postgres(db: AsyncSession, index_key: str, embedding, limit: int) -> list:
    if embedding is None:
        return []
    from pgvector.sqlalchemy import Vector

    from src.backend.search.embeddings import EMBEDDING_DIM

    # `<=>` is pgvector's cosine distance. Applied explicitly rather than via
    # Vector.cosine_distance: the column is a TypeDecorator, which does not
    # inherit the wrapped type's comparator methods. The bind parameter is given
    # the Vector type directly so it is sent as a vector literal, not JSON.
    query_vector = literal(embedding, Vector(EMBEDDING_DIM))
    distance = SearchDocument.embedding.op("<=>", return_type=Float)(query_vector)
    rows = (await db.execute(
        select(SearchDocument.conversation_id)
        .where(SearchDocument.index_key == index_key, SearchDocument.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
    )).scalars().all()
    return list(rows)


async def _search_postgres(
    db: AsyncSession, index_key: str, query: str, embedding, semantic_ratio: float, top_n: int
) -> list[dict]:
    lexical = await _lexical_postgres(db, index_key, query, top_n)
    semantic = await _semantic_postgres(db, index_key, embedding, top_n)
    return _fuse([(LEXICAL_WEIGHT, lexical), (SEMANTIC_WEIGHT, semantic)])


async def _search_python(
    db: AsyncSession, index_key: str, query: str, embedding, semantic_ratio: float, top_n: int
) -> list[dict]:
    """Fallback for SQLite (development and tests), fused the same way.

    BM25 is a PostgreSQL extension, so the lexical tier here is term overlap.
    The fusion is identical, which is what the tests actually exercise.
    """
    documents = (
        await db.execute(select(SearchDocument).where(SearchDocument.index_key == index_key))
    ).scalars().all()

    lexical = [d for d in documents if _keyword_score(d.content, query) > 0]
    lexical.sort(key=lambda d: _keyword_score(d.content, query), reverse=True)

    semantic: list = []
    if embedding is not None:
        scored = [(d, _cosine_similarity(embedding, d.embedding or [])) for d in documents]
        semantic = [d for d, score in sorted(scored, key=lambda x: x[1], reverse=True) if score > 0]

    return _fuse([
        (LEXICAL_WEIGHT, [d.conversation_id for d in lexical[:top_n]]),
        (SEMANTIC_WEIGHT, [d.conversation_id for d in semantic[:top_n]]),
    ])


async def hybrid_search(
    db: AsyncSession,
    index_key: str,
    query: str,
    semantic_ratio: float = DEFAULT_SEMANTIC_RATIO,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """Return matching conversations, best first, fusing both tiers.

    Either tier may return nothing -- no embedding, or no BM25 analyzer -- and
    the other still answers, so search degrades rather than breaking.
    """
    embedding = await embed(query)
    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
    search = _search_postgres if dialect == "postgresql" else _search_python
    # Fuse more candidates per tier than are finally shown.
    results = await search(db, index_key, query, embedding, semantic_ratio, top_n * CANDIDATE_MULTIPLIER)
    return [r for r in results if r["score"] > 0]


def to_conversation_ids_and_scores(results: list[dict]) -> tuple[list, list[float]]:
    return (
        [r["conversation_id"] for r in results],
        [round(r["score"], 3) for r in results],
    )

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

RRF has one sharp edge, and it has bitten this file once: it scores a document
by where it *placed*, not by whether it matched. `ORDER BY ... LIMIT n` always
returns n documents if the table holds n, and RRF then gives every one of them a
positive score -- so on a small table every document was a result for every
query, ordered by the tiers' opinions of each other rather than by the query.
Each tier therefore decides what counts as a match before fusion: exactly 0.0
from BM25 means no shared term, and SEMANTIC_MAX_DISTANCE bounds the vector
tier. Filtering after fusion cannot recover this -- by then a non-match and a
weak match look identical.
"""

import logging
import math

from sqlalchemy import Float, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.fastapi.models import SearchDocument, Session
from src.backend.search.embeddings import embed
from src.config import bot_config

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = bot_config.search.top_n

# Reciprocal Rank Fusion: score = weight / (RRF_K + rank). K damps the influence
# of the very top ranks so a single tier cannot dominate; 60 is the value from
# the original RRF paper and the de facto default.
RRF_K = bot_config.search.rrf_k
LEXICAL_WEIGHT = bot_config.search.weights.lexical
SEMANTIC_WEIGHT = bot_config.search.weights.semantic

# Fusing ranks needs more candidates per tier than are finally shown.
CANDIDATE_MULTIPLIER = 4

# Cosine distance past which a session is not a match at all.
#
# Both tiers return their top N *whatever* is in the table -- that is what
# ORDER BY ... LIMIT means -- and RRF gives every returned row a positive score.
# Without a cutoff, every session in a small table is a "result" for every
# query, ranked by the tiers' opinions of each other rather than by the query.
#
# The number is not a boundary, because there is not one. Measured against real
# session summaries, 14 plausible queries and 58 mismatched pairs:
#
#     query -> the session it belongs to       0.34 - 0.78
#     query -> any other session               0.60 - 0.99
#
# They overlap. The trade is made towards recall, for two reasons. A missed
# semantic hit is invisible forever, while a marginal one enters fusion at a
# low rank and contributes 1/(60+k) -- it can add a weak row at the bottom, and
# it almost never outranks something the lexical tier found. And the lexical
# tier is already the precise half of this design: exact terms, no threshold,
# zero means no shared term.
#
# 0.75 keeps 13 of those 14 true matches and admits 6 of 58 false ones. The
# previous 0.6 kept 8 of 14 -- it was calibrated when this tier embedded
# individual short messages, and a session summary is a long dense paragraph, so
# short-query-to-long-document distance sits systematically higher. The
# threshold did not move when the thing it measures did.
#
# It is a property of the embedding model and the corpus, not a constant. Raise
# for recall, lower for precision.
SEMANTIC_MAX_DISTANCE = bot_config.search.semantic_max_distance


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

    No embedding is generated here any more. Lexical search covers every
    message through a database trigger at no cost, and the semantic tier now
    works from one summary per session rather than one vector per turn -- see
    search/summary.py. ``embedding`` is still accepted so a caller that wants a
    turn-level vector can supply one, and so existing rows keep working.
    """
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
    """BM25 ranking, matches only. Returns [] when the analyzer is absent, so a
    database without analyzer.sql applied degrades to semantic-only rather than
    erroring."""
    # Inside a SAVEPOINT: if BM25 is unavailable the statement fails, and a
    # failed statement aborts the whole transaction -- which would then take the
    # semantic tier down with it, turning graceful degradation into an outage.
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                text(
                    "SELECT conversation_id, bm25 <&> bm25_catalog.to_bm25query("
                    "  'search_documents_bm25_idx', public.to_bm25_query(:q)) AS score "
                    "FROM search_documents "
                    "WHERE index_key = :key AND bm25 IS NOT NULL "
                    "ORDER BY score LIMIT :n"
                ),
                {"key": index_key, "q": query, "n": limit},
            )).all()
        # `<&>` is negative and more negative is more relevant, so exactly 0.0
        # means the document and the query share no term at all. Filtered here
        # rather than in the WHERE clause so the index still drives ORDER BY.
        return [conversation_id for conversation_id, score in rows if score < 0]
    except Exception:
        logger.warning("BM25 ranking unavailable; using semantic only", exc_info=True)
        return []


async def _representative_conversations(
    db: AsyncSession, index_key: str, session_ids: list
) -> dict:
    """The conversation that opened each session, within this index.

    The semantic tier ranks *sessions*, but a result row is a conversation --
    and /resume_session takes a session id anyway. One row per session keeps a
    long session from flooding the results with twenty near-identical hits.
    The opening conversation is the one that introduced the topic.
    """
    if not session_ids:
        return {}
    rows = (await db.execute(
        select(SearchDocument.session_id, SearchDocument.conversation_id)
        .where(SearchDocument.session_id.in_(session_ids),
               SearchDocument.index_key == index_key)
        .order_by(SearchDocument.session_id, SearchDocument.created_at)
    )).all()
    first: dict = {}
    for session_id, conversation_id in rows:
        first.setdefault(session_id, conversation_id)
    return first


async def _semantic_postgres(db: AsyncSession, index_key: str, embedding, limit: int) -> list:
    """Rank session summaries, then map each to a conversation to fuse with.

    Was one vector per turn. A turn-level embedding is generated on every
    message and most turns do not deserve one -- "you good?" embedded to
    something plausible and outranked a genuinely relevant turn, because a short
    aside sits near everything. A summary is dense and topical.
    """
    if embedding is None:
        return []
    from pgvector.sqlalchemy import Vector

    from src.backend.search.embeddings import EMBEDDING_DIM

    # `<=>` is pgvector's cosine distance. Applied explicitly rather than via
    # Vector.cosine_distance: the column is a TypeDecorator, which does not
    # inherit the wrapped type's comparator methods. The bind parameter is given
    # the Vector type directly so it is sent as a vector literal, not JSON.
    query_vector = literal(embedding, Vector(EMBEDDING_DIM))
    distance = Session.summary_vector.op("<=>", return_type=Float)(query_vector)
    # Scoped through search_documents rather than by joining users: index_key is
    # what separates one user's history from another's, and it is already on
    # every indexed row.
    in_scope = select(SearchDocument.session_id).where(SearchDocument.index_key == index_key)
    rows = (await db.execute(
        select(Session.id, distance.label("distance"))
        .where(Session.summary_vector.isnot(None), Session.id.in_(in_scope))
        .order_by(distance)
        .limit(limit)
    )).all()
    # Filtered after ordering, not in the WHERE clause, so a vector index can
    # still serve the ORDER BY.
    ranked = [session_id for session_id, d in rows if d <= SEMANTIC_MAX_DISTANCE]
    representative = await _representative_conversations(db, index_key, ranked)
    return [representative[s] for s in ranked if s in representative]


async def _search_postgres(
    db: AsyncSession, index_key: str, query: str, embedding, top_n: int
) -> list[dict]:
    lexical = await _lexical_postgres(db, index_key, query, top_n)
    semantic = await _semantic_postgres(db, index_key, embedding, top_n)
    return _fuse([(LEXICAL_WEIGHT, lexical), (SEMANTIC_WEIGHT, semantic)])


async def _search_python(
    db: AsyncSession, index_key: str, query: str, embedding, top_n: int
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

    semantic_conversations: list = []
    if embedding is not None:
        in_scope = {d.session_id for d in documents}
        sessions = (await db.execute(
            select(Session).where(Session.id.in_(in_scope), Session.summary_vector.isnot(None))
        )).scalars().all()
        scored = [(s, _cosine_similarity(embedding, s.summary_vector or [])) for s in sessions]
        # Same cutoff as PostgreSQL, expressed as similarity rather than
        # distance, so both paths agree about what counts as a match.
        ranked = [
            s.id for s, score in sorted(scored, key=lambda x: x[1], reverse=True)
            if score >= 1.0 - SEMANTIC_MAX_DISTANCE
        ]
        representative = await _representative_conversations(db, index_key, ranked)
        semantic_conversations = [representative[s] for s in ranked if s in representative][:top_n]

    return _fuse([
        (LEXICAL_WEIGHT, [d.conversation_id for d in lexical[:top_n]]),
        (SEMANTIC_WEIGHT, semantic_conversations),
    ])


async def hybrid_search(
    db: AsyncSession,
    index_key: str,
    query: str,
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
    return await search(
        db, index_key, query, embedding, top_n * CANDIDATE_MULTIPLIER
    )


def to_conversation_ids_and_scores(results: list[dict]) -> tuple[list, list[float]]:
    return (
        [r["conversation_id"] for r in results],
        [round(r["score"], 3) for r in results],
    )

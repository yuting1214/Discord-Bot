"""Reciprocal Rank Fusion.

The previous scoring was a weighted sum of cosine similarity and ts_rank. Those
live on incomparable scales -- cosine lands around 0.3-0.5, ts_rank around 0.05 --
so a nominal 50/50 split behaved as roughly 90% semantic. RRF combines ranks,
which have no scale to mismatch.
"""

import pytest

from src.backend.search.service import RRF_K, _fuse


def ids(fused):
    return [f["conversation_id"] for f in fused]


def test_a_document_ranked_first_by_both_tiers_wins():
    fused = _fuse([(1.0, ["a", "b", "c"]), (1.0, ["a", "c", "b"])])
    assert ids(fused)[0] == "a"


def test_agreement_beats_a_single_strong_ranking():
    """b is second in both; a is first in one and absent from the other."""
    fused = _fuse([(1.0, ["a", "b"]), (1.0, ["c", "b"])])
    assert ids(fused)[0] == "b", ids(fused)


def test_scale_cannot_dominate_the_way_a_weighted_sum_could():
    """Only rank position matters, so no tier can swamp the other by magnitude."""
    fused = _fuse([(1.0, ["x"]), (1.0, ["y"])])
    scores = {f["conversation_id"]: f["score"] for f in fused}
    assert scores["x"] == scores["y"] == 1.0 / (RRF_K + 1)


def test_weights_still_break_ties():
    fused = _fuse([(2.0, ["lex"]), (1.0, ["sem"])])
    assert ids(fused) == ["lex", "sem"]


def test_one_empty_tier_still_returns_the_other():
    """Either tier can be unavailable -- no embedding, or no BM25 analyzer."""
    assert ids(_fuse([(1.0, []), (1.0, ["only"])])) == ["only"]
    assert ids(_fuse([(1.0, ["only"]), (1.0, [])])) == ["only"]
    assert _fuse([(1.0, []), (1.0, [])]) == []


def test_every_fused_score_is_positive():
    """Every document a tier returns gets a positive score, whether or not it
    matched. That is why the tiers must decide what counts as a match before
    fusion -- see test_a_document_matching_nothing_never_reaches_fusion."""
    fused = _fuse([(1.0, list("abcdefghij")), (1.0, list("jihgfedcba"))])
    assert all(f["score"] > 0 for f in fused)
    assert len(fused) == 10


def test_results_are_sorted_best_first():
    fused = _fuse([(1.0, ["a", "b", "c"]), (1.0, ["a", "b", "c"])])
    assert [f["score"] for f in fused] == sorted((f["score"] for f in fused), reverse=True)


class _FailingSession:
    """A session whose BM25 statement raises, as it would without the extension."""

    def __init__(self):
        self.savepoints = 0

    def begin_nested(self):
        session = self

        class _Savepoint:
            async def __aenter__(self):
                session.savepoints += 1
                return self

            async def __aexit__(self, *exc):
                return False

        return _Savepoint()

    async def execute(self, *a, **k):
        raise RuntimeError('type "bm25vector" does not exist')


@pytest.mark.asyncio
async def test_a_bm25_failure_is_contained_and_returns_no_hits():
    """A failed statement aborts the whole PostgreSQL transaction, so without a
    SAVEPOINT a BM25 failure also killed the semantic tier -- turning graceful
    degradation into an outage. Verified against a real database: with the
    savepoint, the semantic tier still answered in the same session."""
    from src.backend.search.service import _lexical_postgres

    session = _FailingSession()
    hits = await _lexical_postgres(session, "key", "query", 5)

    assert hits == [], "a BM25 failure must degrade to no lexical hits, not raise"
    assert session.savepoints == 1, "the query must run inside a SAVEPOINT"


# ---------------------------------------------------------------------------
# Match cutoffs
# ---------------------------------------------------------------------------
# Found in production, not by these tests: on a 7-document table every query
# returned 5 results with scores inside a 0.002 band, and one document sat at
# rank 2 for every query including ones sharing no character with it. Both tiers
# were returning their whole ORDER BY ... LIMIT window and RRF was scoring all
# of it. The SQLite fallback had always filtered; only the PostgreSQL path did
# not, so no test covered the paths that shipped.


class _RowSession:
    """A session that returns each supplied result set in turn.

    The semantic tier issues two queries -- rank the sessions, then map each to
    the conversation that opened it -- so a fake returning one fixed result for
    every execute() would feed distances in where conversation ids belong.
    """

    def __init__(self, *result_sets):
        self.result_sets = list(result_sets)

    def begin_nested(self):
        class _Savepoint:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        return _Savepoint()

    async def execute(self, *a, **k):
        rows = self.result_sets.pop(0) if self.result_sets else []

        class _Result:
            def all(self):
                return rows

        return _Result()


@pytest.mark.asyncio
async def test_a_bm25_score_of_zero_is_not_a_lexical_hit():
    """`<&>` is negative and more negative is more relevant, so exactly 0.0 means
    the document and the query have no term in common. Measured on live data: for
    every query, exactly one document scored non-zero and the rest were 0.0000 --
    including a decoy containing both characters of the query but not the word."""
    from src.backend.search.service import _lexical_postgres

    session = _RowSession([("match", -1.4386), ("decoy", -0.0), ("other", 0.0)])
    assert await _lexical_postgres(session, "key", "麵包", 20) == ["match"]


@pytest.mark.asyncio
async def test_a_distant_embedding_is_not_a_semantic_hit():
    """Measured on live data: true matches landed at 0.20-0.58 cosine distance,
    unrelated documents at 0.61-0.95, and every document was >= 0.89 away from a
    query about something the corpus never mentioned."""
    from src.backend.search import service

    session = _RowSession(
        # session id -> cosine distance
        [("near", 0.40), ("edge", 0.60), ("far", 0.61), ("miss", 0.95)],
        # session id -> the conversation that opened it
        [("near", "conv-near"), ("edge", "conv-edge"), ("far", "conv-far"), ("miss", "conv-miss")],
    )
    hits = await service._semantic_postgres(session, "key", [0.1] * 1536, 20)
    assert hits == ["conv-near", "conv-edge"], hits


@pytest.mark.asyncio
async def test_a_document_matching_nothing_never_reaches_fusion():
    """The regression, end to end at the fusion boundary: a document that neither
    tier admits must be absent, not merely last. Ranked last still reads to a user
    as a result, and RRF gives it a score inside a rounding error of the real one."""
    from src.backend.search import service

    lexical = await service._lexical_postgres(
        _RowSession([("match", -1.44), ("unrelated", 0.0)]), "key", "q", 20
    )
    semantic = await service._semantic_postgres(
        _RowSession(
            [("session-match", 0.40), ("session-unrelated", 0.86)],
            [("session-match", "match"), ("session-unrelated", "unrelated")],
        ),
        "key", [0.1] * 1536, 20,
    )
    fused = _fuse([(1.0, lexical), (1.0, semantic)])

    assert ids(fused) == ["match"]
    assert "unrelated" not in ids(fused)


def test_both_backends_agree_on_what_counts_as_a_semantic_match():
    """SQLite expresses the cutoff as similarity and PostgreSQL as distance. They
    have to mean the same thing, or development and production disagree about
    which documents exist."""
    from src.backend.search.service import SEMANTIC_MAX_DISTANCE

    similarity_cutoff = 1.0 - SEMANTIC_MAX_DISTANCE
    for distance in (0.0, 0.3, SEMANTIC_MAX_DISTANCE, 0.8, 1.0):
        postgres_keeps = distance <= SEMANTIC_MAX_DISTANCE
        sqlite_keeps = (1.0 - distance) >= similarity_cutoff
        assert postgres_keeps == sqlite_keeps, distance

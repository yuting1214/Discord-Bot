"""Reciprocal Rank Fusion.

The previous scoring was a weighted sum of cosine similarity and ts_rank. Those
live on incomparable scales -- cosine lands around 0.3-0.5, ts_rank around 0.05 --
so a nominal 50/50 split behaved as roughly 90% semantic. RRF combines ranks,
which have no scale to mismatch.
"""

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
    """hybrid_search filters on score > 0, so RRF must never emit zero."""
    fused = _fuse([(1.0, list("abcdefghij")), (1.0, list("jihgfedcba"))])
    assert all(f["score"] > 0 for f in fused)
    assert len(fused) == 10


def test_results_are_sorted_best_first():
    fused = _fuse([(1.0, ["a", "b", "c"]), (1.0, ["a", "b", "c"])])
    assert [f["score"] for f in fused] == sorted((f["score"] for f in fused), reverse=True)

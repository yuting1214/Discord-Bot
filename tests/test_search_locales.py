"""The multilingual corpus, run as a test when a database is available.

    docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=pw postgres-bm25
    BM25_TEST_DSN=postgresql://postgres:pw@localhost:55432/postgres uv run pytest

Skipped without one. The corpus and the assertions live in bench/ so they can
also be run directly against a deployed database -- this file only wires them
into the suite.
"""

import os

import pytest

DSN = os.getenv("BM25_TEST_DSN")

pytestmark = pytest.mark.skipif(
    not DSN, reason="set BM25_TEST_DSN to a scratch PostgreSQL with vchord_bm25"
)


async def test_every_locale_ranks_and_tokenizes_correctly(capsys):
    from bench.search_locales import run

    failures = await run(DSN, reset=True)
    report = capsys.readouterr().out
    assert failures == 0, f"\n{report}"

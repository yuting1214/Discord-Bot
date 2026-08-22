"""Multilingual search verification for the BM25 analyzer.

Runs `bench/corpus.json` against a live PostgreSQL and reports, per locale,
whether the right document ranks first and whether the near-misses score zero.

    uv run python -m bench.search_locales postgresql://…/scratch

The relevance judgements are data, the assertions are here, and neither is in
the application. Adding a language means editing corpus.json.

The target database is written to: this creates and drops its own table, and
`--reset` truncates the shared vocabulary. Point it at a scratch database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg

CORPUS = Path(__file__).with_name("corpus.json")
ANALYZER = Path(__file__).resolve().parents[1] / "src" / "backend" / "search" / "analyzer.sql"

TABLE = "bench_documents"
INDEX = f"{TABLE}_bm25_idx"

SETUP = f"""
DROP TABLE IF EXISTS {TABLE} CASCADE;
CREATE TABLE {TABLE} (
    id      serial PRIMARY KEY,
    locale  text NOT NULL,
    content text NOT NULL,
    bm25    bm25_catalog.bm25vector
);

CREATE OR REPLACE FUNCTION {TABLE}_trg() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN NEW.bm25 := public.to_bm25(NEW.content); RETURN NEW; END $fn$;

CREATE TRIGGER {TABLE}_bm25 BEFORE INSERT OR UPDATE OF content ON {TABLE}
  FOR EACH ROW EXECUTE FUNCTION {TABLE}_trg();
"""

@dataclass
class Result:
    locale: str
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


async def _scores(conn: asyncpg.Connection, query: str) -> list[tuple[str, float]]:
    rows = await conn.fetch(
        f"""
        SELECT content,
               (bm25 <&> bm25_catalog.to_bm25query($1, public.to_bm25_query($2)))::float8 AS score
        FROM {TABLE}
        ORDER BY score
        """,
        INDEX, query,
    )
    return [(r["content"], r["score"]) for r in rows]


async def _segmenter_used(conn: asyncpg.Connection, text: str) -> str:
    """Which path the analyzer actually took for `text`.

    Inferred rather than instrumented: bigrams are, by construction, every
    adjacent character pair, so if the tokens are all length<=2 and cover the
    pairs, it bigrammed. ICU emits variable-length dictionary words.
    """
    try:
        runs = await conn.fetch("SELECT run FROM public.bm25_runs($1)", text)
    except asyncpg.exceptions.UndefinedFunctionError:
        # An older analyzer, or a database that never had one. Report it rather
        # than aborting the run: the point of this harness is to say what a
        # given deployment does, including "not this".
        return "unavailable"
    if not runs:
        return "tsvector"
    run = runs[0]["run"]
    tokens = [
        r["term"] for r in await conn.fetch("SELECT term FROM public.bm25_terms($1)", run)
    ]
    if not tokens:
        return "none"
    expected_bigrams = {run[i:i + 2] for i in range(max(len(run) - 1, 1))}
    return "bigram" if set(tokens) == expected_bigrams else "icu"


async def check_locales(conn: asyncpg.Connection, corpus: dict) -> list[Result]:
    results = []
    for entry in corpus["locales"]:
        result = Result(locale=entry["locale"])

        used = await _segmenter_used(conn, entry["documents"][0])
        if used == entry["segmenter"]:
            result.passed.append(f"segmenter is {used}")
        else:
            result.failed.append(f"segmenter is {used}, expected {entry['segmenter']}")

        for case in entry["cases"]:
            scores = await _scores(conn, case["query"])
            ranked = [c for c, _ in scores]
            by_content = dict(scores)

            top = ranked[0] if ranked else None
            if top == case["expect_top"]:
                result.passed.append(f"{case['query']!r} ranks the right document first")
            else:
                result.failed.append(
                    f"{case['query']!r} ranked {top!r} first, expected {case['expect_top']!r}"
                    f" ({case['why']})"
                )

            for decoy in case["expect_zero"]:
                score = by_content.get(decoy)
                if score is None:
                    result.failed.append(f"decoy missing from the corpus: {decoy!r}")
                elif score == 0.0:
                    result.passed.append(f"{case['query']!r} scores the decoy zero")
                else:
                    result.failed.append(
                        f"{case['query']!r} scored decoy {decoy!r} at {score:.4f}, expected 0"
                        f" ({case['why']})"
                    )
        results.append(result)
    return results


async def check_tokenization(conn: asyncpg.Connection, corpus: dict) -> Result:
    """Term-level judgements: scripts mixed inside one document, and the tokens
    the analyzer must refuse because each one costs ~8KB of index."""
    result = Result(locale="tokenization")
    for case in corpus["tokenization"]:
        rows = await conn.fetch("SELECT term FROM public.bm25_terms($1)", case["text"])
        terms = {r["term"] for r in rows}
        for term in case["must_contain"]:
            if term in terms:
                result.passed.append(f"{term!r} kept")
            else:
                result.failed.append(
                    f"{case['text']!r} dropped {term!r}; got {sorted(terms)}"
                    f" ({case['why']})"
                )
        for term in case["must_not_contain"]:
            if term in terms:
                result.failed.append(
                    f"{case['text']!r} admitted {term!r} to the vocabulary ({case['why']})"
                )
            else:
                result.passed.append(f"{term!r} kept out")
    return result


async def check_highlighting(conn: asyncpg.Connection, corpus: dict) -> Result:
    """What a search box shows. A document that ranked correctly and comes back
    with nothing marked reads as broken, and that is exactly what plain
    ts_headline does to every script this analyzer exists for."""
    result = Result(locale="highlighting")
    for case in corpus["highlighting"]:
        marked = await conn.fetchval(
            "SELECT public.bm25_headline($1, $2, '<<', '>>')", case["text"], case["query"]
        )
        found = {
            marked[i + 2 : marked.index(">>", i)]
            for i in range(len(marked))
            if marked.startswith("<<", i)
        }
        for expected in case["expect_marked"]:
            if expected in found:
                result.passed.append(f"{case['query']!r} marks {expected!r}")
            else:
                result.failed.append(
                    f"{case['query']!r} on {case['text']!r} marked {sorted(found)},"
                    f" expected {expected!r} ({case['why']})"
                )
        if not case["expect_marked"]:
            if found:
                result.failed.append(
                    f"{case['query']!r} marked {sorted(found)} in a decoy ({case['why']})"
                )
            else:
                result.passed.append(f"{case['query']!r} marks nothing in the decoy")
    return result


async def run(dsn: str, reset: bool = False) -> int:
    corpus = json.loads(CORPUS.read_text())
    conn = await asyncpg.connect(dsn, server_settings={"search_path": "public,bm25_catalog"})
    try:
        await conn.execute(ANALYZER.read_text())
        if reset:
            await conn.execute("TRUNCATE public.bm25_vocabulary RESTART IDENTITY CASCADE")
        await conn.execute(SETUP)

        rows = [
            (entry["locale"], doc)
            for entry in corpus["locales"]
            for doc in entry["documents"]
        ]
        await conn.executemany(f"INSERT INTO {TABLE} (locale, content) VALUES ($1, $2)", rows)
        await conn.execute(
            f"CREATE INDEX {INDEX} ON {TABLE} USING bm25 (bm25 bm25_catalog.bm25_ops)"
        )

        results = await check_locales(conn, corpus)
        results.append(await check_tokenization(conn, corpus))
        results.append(await check_highlighting(conn, corpus))

        vocabulary = await conn.fetchval("SELECT count(*) FROM public.bm25_vocabulary")
        index_size = await conn.fetchval(f"SELECT pg_size_pretty(pg_relation_size('{INDEX}'))")
    finally:
        await conn.close()

    width = max(len(r.locale) for r in results)
    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'}  {r.locale:<{width}}  {len(r.passed)} checks")
        for failure in r.failed:
            print(f"        {failure}")

    failed = [r for r in results if not r.ok]
    print(f"\n{len(rows)} documents, {vocabulary} vocabulary terms, {index_size} index")
    print(f"{len(results) - len(failed)}/{len(results)} groups passed")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dsn", nargs="?", default=os.getenv("BM25_TEST_DSN"),
        help="PostgreSQL DSN of a scratch database (or set BM25_TEST_DSN)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="truncate bm25_vocabulary first, for reproducible index-size numbers",
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error("pass a DSN or set BM25_TEST_DSN")
    return asyncio.run(run(args.dsn, args.reset))


if __name__ == "__main__":
    sys.exit(main())

# postgres-bm25

PostgreSQL for this template: **pgvector + BM25**, built on Railway's own image.

## Why this exists

`ghcr.io/railwayapp-templates/postgres-ssl` is not plain Postgres — it bundles
pgvector, pgBackRest backups and the SSL wrapper. Adopting a third-party search
image such as `paradedb/paradedb` would trade all of that away to gain one
extension, so BM25 is layered on top instead.

VectorChord rather than ParadeDB's `pg_search` — but **not** for packaging reasons.
An earlier version of this document claimed `pg_search` ships Linux RPMs only. That
was wrong: it publishes 32 Debian packages per release, including
`postgresql-18-pg-search_0.25.3-1PARADEDB-trixie_amd64.deb`, which matches this base
exactly. The error came from reading a truncated listing of the release assets.

The real reasons:

| | ParadeDB `pg_search` | VectorChord `vchord_bm25` |
|---|---|---|
| Licence | **AGPL-3.0** | permissive |
| Shared object | ~143 MB | ~2 MB |
| Idle memory | comparable — see below | comparable |

Licence is the deciding factor. This image exists to be deployed by other people,
and AGPL-3.0 on the database engine is a constraint many of them cannot accept.

## What's inside

| | version |
|---|---|
| PostgreSQL | 18.6 (Railway `postgres-ssl`) |
| pgvector | 0.8.6 |
| vchord_bm25 | 0.3.0 |
| pgBackRest | 2.59.1 — Railway's backup tooling, retained |

## Memory

Idle anon memory, identical conditions, measured natively:

| configuration | idle |
|---|---|
| stock Railway `postgres-ssl` | 6.4 MB |
| **+ vchord_bm25 — this image** | **6.5 MB** |
| + pg_tokenizer | 337.5 MB |

`pg_tokenizer` costs **~331 MB** and is deliberately **not** installed.

> **Read this figure correctly.** 6.5 MB is *anon* memory at idle on an empty
> database. Total cgroup memory after a realistic 20,000-document workload is
> **87.6 MB**, against **95.4 MB** for the same workload on `pg_search`. The honest
> comparison against a BM25 competitor is roughly **8% better, not 50× better**.
> The 50× figure only describes the gap against `pg_tokenizer` at idle, which is an
> *allocation* penalty from preloading models — not a property of BM25 itself. BM25 needs a `bm25vector` — a sparse
`{term_id:frequency}` map — but nothing requires that vector to come from
`pg_tokenizer`. Postgres' own text search produces the same thing for a rounding
error in memory.

> Measure natively. On Apple Silicon, `--platform linux/amd64` runs under Rosetta
> and inflated every reading roughly 5× (6.4 MB read as 30.7 MB).

## Tokenizing without pg_tokenizer

Apply [`analyzer.sql`](../../src/backend/search/analyzer.sql), which ships with the
application and is applied automatically at startup. It is idempotent:

```bash
psql "$DATABASE_URL" -f analyzer.sql
```

It creates a `bm25_vocabulary` table mapping terms to stable ids, and three
functions:

| function | volatility | use |
|---|---|---|
| `bm25_terms(text)` | IMMUTABLE | Latin via `to_tsvector`, CJK via bigrams |
| `to_bm25(text)` | VOLATILE | **write path** — extends the vocabulary |
| `to_bm25_query(text)` | STABLE | **read path** — lookup only, never writes |

The split matters. An earlier version extended the vocabulary on query too, which
makes the function VOLATILE, and the planner then re-evaluates it once per row
rather than once per query: **106 ms per search instead of 6.5 ms**. Unknown query
terms now simply match nothing, which is correct BM25 behaviour.

Attach it to a table:

```sql
ALTER TABLE messages ADD COLUMN bm25 bm25_catalog.bm25vector;

CREATE FUNCTION messages_bm25_trg() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN NEW.bm25 := public.to_bm25(NEW.content); RETURN NEW; END $fn$;

CREATE TRIGGER messages_bm25 BEFORE INSERT OR UPDATE OF content ON messages
  FOR EACH ROW EXECUTE FUNCTION messages_bm25_trg();

CREATE INDEX messages_bm25_idx ON messages USING bm25 (bm25 bm25_catalog.bm25_ops);
```

Query — `<&>` returns *negative* scores, more negative is more relevant, so order
ascending. Put `bm25_catalog` on the `search_path`: vchord's own operators resolve
their types against it.

```sql
SET search_path TO public, bm25_catalog;

SELECT id FROM messages
ORDER BY bm25 <&> bm25_catalog.to_bm25query('messages_bm25_idx',
                                            public.to_bm25_query('search terms'))
LIMIT 5;
```

### CJK: bigrams, and why they beat pg_tokenizer here

Postgres' text search does not segment Chinese, Japanese or Korean, so CJK runs
are indexed as overlapping character **bigrams** — the strategy Lucene's
CJKAnalyzer uses. `analyzer.sql` does this automatically.

That is not a compromise. `pg_tokenizer`'s `unicode_segmentation` emits character
**unigrams**, and individual CJK characters are far too common to discriminate.
Measured on a corpus with two decoys containing 麵 and 包 non-adjacently, query
`麵包` (bread):

| analyzer | rank 1 | rank 2 | rank 3 |
|---|---|---|---|
| pg_tokenizer (unigrams) | ✗ 這家**麵**店的**包**子 `-0.7409` | ✗ **包**裝這個**麵**條 `-0.7134` | ✓ 酸種**麵包** `-0.6418` |
| this image (bigrams) | ✓ 酸種**麵包** `-1.0724` | `0.0000` | `0.0000` |

pg_tokenizer ranks **both decoys above the correct document**. Proper CJK word
segmentation from pg_tokenizer needs a Lindera model on top, which is more
configuration and more memory again.

### Benchmark

20,000 mixed English/Chinese documents, identical corpus and queries, native arm64:

| | pg_tokenizer | this image |
|---|---|---|
| idle memory | 336.6 MB | **6.5 MB** |
| after workload | 336.9 MB | **6.8 MB** |
| ingest 20k docs | **3.5 s** | 12.3 s |
| index build | **368 ms** | 418 ms |
| search, 200 varying queries | **0.37 ms** each | 6.5 ms each |
| tokenize only, per call | **0.03 ms** | 0.94 ms |
| CJK precision | ✗ decoys outrank | ✓ correct |

pg_tokenizer is genuinely faster — roughly 17× per search and 3.5× on ingest. The
trade is 330 MB of permanently resident memory and worse CJK ranking. At 6.5 ms a
search this is not a bottleneck for a chat application, and the memory is the
difference between a database service that is cheap to leave running and one that
is not. If your workload is high-QPS search where 6 ms matters more than 330 MB,
install pg_tokenizer and configure a Lindera model for CJK.

### What Postgres alone does with CJK

For reference, this is why the bigram step exists — `to_tsvector` on its own
collapses a whole CJK phrase into one unusable token:

```
to_tsvector('english', 'sourdough bread starter')
  -> 'bread':2 'sourdough':1 'starter':3          ✓ stemmed, stopworded

to_tsvector('english', '我想要一個關於酸種麵包的建議')
  -> '我想要一個關於酸種麵包的建議':1                  ✗ one token
```

`bm25_terms` splits CJK runs out before calling `to_tsvector` and emits bigrams
for them, so both scripts are handled in one pass.

## Known issue: index size scales with vocabulary, not corpus

`vchord_bm25` allocates roughly **8 KB per distinct vocabulary term**, largely
independent of how many documents contain it. This is measurable in this repo's own
benchmark: 20,000 documents produced 20,079 distinct terms and a **161 MB** index —
8.0 KB per term.

That benchmark's corpus appended a unique number to every document, which looked like
an artifact at the time. It is not an artifact; it is the pathological case, and it is
a realistic one. Chat and log data are full of high-cardinality tokens — usernames,
URLs, IDs, hashes — and every one becomes a permanent vocabulary entry.

| corpus shape | distinct terms | index | container |
|---|---|---|---|
| ordinary prose | ~5,000 | 1.3 MB | 88 MB |
| one unique token per document | 20,000 | **157 MB** | **416 MB** |

For comparison, `pg_search` indexed the same high-cardinality corpus in 3.2 MB.

**Mitigation before this is used at scale:** apply a document-frequency floor in
`bm25_terms` so tokens appearing in fewer than N documents are not admitted to the
vocabulary, and/or strip URL, numeric and hash-shaped tokens. Not yet implemented —
tracked for v0.3.0.

## Build

```bash
docker build --platform linux/amd64 -t postgres-bm25 .

# A different PostgreSQL major:
docker build --build-arg PG_MAJOR=17 --build-arg PG_TAG=17.11 -t postgres-bm25:pg17 .
```

## Things that will bite you

**The extension must be preloaded.** `shared_preload_libraries=vchord_bm25` is baked
into the image's `CMD`. Do **not** override the command at deploy time: Railway's
entrypoint is `wrapper.sh`, and replacing the command drops the arguments it needs
(`-p 5432 -c listen_addresses=*`), after which the server never starts.

**It installs into its own schema.** `vchord_bm25` lives in `bm25_catalog`, not
`public`. Qualify calls or set `search_path`.

**`bm25vector` literals are sparse and must be sorted.** `'{1:2, 4:1}'` is a
`{term_id:frequency}` map; unsorted ids fail with
`Indexes are not increasing at position N`, and a plain `'{1,2,3}'` array fails with
`Missing colon at position N`.

**Wait for the container to finish initialising.** The Postgres image runs a
temporary server during first-time init, then shuts it down and restarts. A query
issued during that window dies with `server closed the connection unexpectedly`,
which looks exactly like a crash and is not one.

## Verified

Built for `linux/amd64` and `linux/arm64`, deployed to Railway, and exercised
against a 20,005 row corpus:

- The extension loads with the baked `CMD` and no deploy-time override
- The trigger populates the BM25 vector on insert for every row
- The planner uses `Index Scan using ..._bm25_idx`; 33 ms for a top-5 query
- `uuidv7()` is available natively on PostgreSQL 18
- pgBackRest survives the added layer
- Ranking is correct on real data: a content-free row (`"you good?"`) scores exactly
  `0.0000` for an unrelated query, where embedding search scored it *above* a
  genuinely relevant row. That complementary failure mode is why both tiers exist.

# postgres-bm25

PostgreSQL for this template: **pgvector + BM25**, built on Railway's own image.

## Why this exists

`ghcr.io/railwayapp-templates/postgres-ssl` is not plain Postgres — it bundles
pgvector, pgBackRest backups and the SSL wrapper. Adopting a third-party search
image such as `paradedb/paradedb` would trade all of that away to gain one
extension, so the BM25 extensions are layered on top instead.

VectorChord rather than ParadeDB's `pg_search`, purely on packaging: `pg_search`
publishes Linux **RPMs** only and this base is Debian, so using it would mean
compiling Rust/pgrx from source. VectorChord ships `.deb` for pg14–18.

## What's inside

| | version |
|---|---|
| PostgreSQL | 18.6 (Railway `postgres-ssl`) |
| pgvector | 0.8.6 |
| vchord_bm25 | 0.3.0 |
| pg_tokenizer | 0.1.1 |
| pgBackRest | 2.59.1 — Railway's backup tooling, retained |

## Build

```bash
docker build --platform linux/amd64 -t postgres-bm25 .

# Pin a different PostgreSQL major:
docker build --build-arg PG_MAJOR=17 --build-arg PG_TAG=17.11 -t postgres-bm25:pg17 .
```

## Enabling the extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_tokenizer CASCADE;
CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;
```

## Things that will bite you

**The extensions must be preloaded.** `shared_preload_libraries` is baked into the
image's `CMD`. Do **not** override the command at deploy time: Railway's entrypoint
is `wrapper.sh`, and replacing the command drops the arguments it needs
(`-p 5432 -c listen_addresses=*`), after which the server never starts.

**They install into their own schemas**, not `public`:

| extension | schema |
|---|---|
| `vector` | `public` |
| `pg_tokenizer` | `tokenizer_catalog` |
| `vchord_bm25` | `bm25_catalog` |

Qualify every call, or set `search_path`.

**The published VectorChord docs are out of date.** They show
`create_tokenizer('name', $$ tokenizer = 'unicode' ... $$)`, which 0.3.0 rejects with
`missing field 'model'`. The current flow is:

```sql
SELECT tokenizer_catalog.create_text_analyzer('ta', $$
pre_tokenizer = "unicode_segmentation"
[[character_filters]]
to_lowercase = {}
[[token_filters]]
stemmer = "english_porter2"
$$);

SELECT tokenizer_catalog.create_custom_model_tokenizer_and_trigger(
  tokenizer_name => 'tk', model_name => 'm', text_analyzer_name => 'ta',
  table_name => 'documents', source_column => 'content', target_column => 'bm25');

CREATE INDEX ON documents USING bm25 (bm25 bm25_catalog.bm25_ops);
```

The trigger keeps the BM25 column current on insert and update, so nothing in the
application has to remember to tokenize.

**Querying.** `<&>` returns *negative* scores — more negative is more relevant — so
order ascending:

```sql
SELECT id
FROM documents
ORDER BY bm25 <&> bm25_catalog.to_bm25query(
  'documents_bm25_idx', tokenizer_catalog.tokenize('search terms', 'tk'))
LIMIT 5;
```

## Verified

Built for `linux/amd64` and exercised against a 20,005 row corpus:

- All three extensions load with the baked `CMD`, no override
- The trigger populated every row's BM25 vector on insert
- The planner uses `Index Scan using ..._bm25_idx`; 33 ms for a top-5 query
- `uuidv7()` is available natively on PostgreSQL 18
- pgBackRest survives the added layer

A content-free row (`"you good?"`) scores exactly `0.0000` for an unrelated query,
where embedding-based search scored it above a genuinely relevant row. That
complementary failure mode is the reason both tiers exist.

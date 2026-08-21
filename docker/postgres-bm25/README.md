# postgres-bm25

PostgreSQL for this template: **pgvector + BM25**, built on Railway's own image.

## Why this exists

`ghcr.io/railwayapp-templates/postgres-ssl` is not plain Postgres — it bundles
pgvector, pgBackRest backups and the SSL wrapper. Adopting a third-party search
image such as `paradedb/paradedb` would trade all of that away to gain one
extension, so BM25 is layered on top instead.

VectorChord rather than ParadeDB's `pg_search`, purely on packaging: `pg_search`
publishes Linux **RPMs** only and this base is Debian, so using it would mean
compiling Rust/pgrx from source. VectorChord ships `.deb` for pg14–18.

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

`pg_tokenizer` costs **~331 MB** because it preloads tokenizer models, and it is
deliberately **not** installed. BM25 needs a `bm25vector` — a sparse
`{term_id:frequency}` map — but nothing requires that vector to come from
`pg_tokenizer`. Postgres' own text search produces the same thing for a rounding
error in memory.

> Measure natively. On Apple Silicon, `--platform linux/amd64` runs under Rosetta
> and inflated every reading roughly 5× (6.4 MB read as 30.7 MB).

## Tokenizing without pg_tokenizer

A vocabulary table maps terms to stable ids; `to_tsvector` supplies stemming and
stopwords; a trigger keeps the column current.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;

CREATE TABLE bm25_vocabulary (id serial PRIMARY KEY, term text UNIQUE NOT NULL);

CREATE FUNCTION to_bm25(content text, cfg regconfig DEFAULT 'english')
RETURNS bm25_catalog.bm25vector LANGUAGE plpgsql AS $$
DECLARE result bm25_catalog.bm25vector;
BEGIN
  INSERT INTO bm25_vocabulary (term)
  SELECT DISTINCT lexeme FROM unnest(to_tsvector(cfg, content))
  ON CONFLICT (term) DO NOTHING;

  -- term ids must be ascending; the type rejects unsorted input
  SELECT COALESCE('{' || string_agg(v.id || ':' || t.freq, ', ' ORDER BY v.id) || '}', '{}')
           ::bm25_catalog.bm25vector
  INTO result
  FROM (SELECT lexeme, cardinality(positions) AS freq
        FROM unnest(to_tsvector(cfg, content))) t
  JOIN bm25_vocabulary v ON v.term = t.lexeme;
  RETURN result;
END $$;
```

Attach it to a table:

```sql
ALTER TABLE messages ADD COLUMN bm25 bm25_catalog.bm25vector;

CREATE FUNCTION messages_bm25_trg() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.bm25 := to_bm25(NEW.content); RETURN NEW; END $$;

CREATE TRIGGER messages_bm25 BEFORE INSERT OR UPDATE OF content ON messages
  FOR EACH ROW EXECUTE FUNCTION messages_bm25_trg();

CREATE INDEX messages_bm25_idx ON messages USING bm25 (bm25 bm25_catalog.bm25_ops);
```

Query — `<&>` returns *negative* scores, more negative is more relevant, so order
ascending:

```sql
SELECT id
FROM messages
ORDER BY bm25 <&> bm25_catalog.to_bm25query('messages_bm25_idx', to_bm25('search terms'))
LIMIT 5;
```

### The CJK trade-off

This is the one thing `pg_tokenizer` bought that Postgres does not replace.
Postgres' text search does not segment Chinese, Japanese or Korean:

```
to_tsvector('english', 'sourdough bread starter')
  -> 'bread':2 'sourdough':1 'starter':3          ✓ stemmed, stopworded

to_tsvector('english', '我想要一個關於酸種麵包的建議')
  -> '我想要一個關於酸種麟包的建議':1                  ✗ one token, unsearchable

to_tsvector('english', '幫我寫一個 Discord bot 教學')
  -> 'bot':3 'discord':2 '幫我寫一個':1 '教學':4      ~ latin terms still indexed
```

So **lexical search is effectively English-only** here. That is an acceptable
default for this template because retrieval is two-tier: CJK queries are served by
the semantic tier, where embeddings handle Chinese well, and mixed-script text
still gets its Latin terms indexed.

If CJK lexical search matters for your deployment, either install `pg_tokenizer`
and accept the ~331 MB (it carries Lindera models), or add a bigram extension such
as `pg_bigm`, which is far smaller.

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

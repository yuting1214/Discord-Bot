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
| `bm25_script_class()` | IMMUTABLE | the character ranges routed to bigrams |
| `bm25_terms(text)` | IMMUTABLE | spaced scripts via `to_tsvector`, unspaced via bigrams |
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

### Unspaced scripts: bigrams, and why they beat pg_tokenizer here

Postgres' text search cannot segment scripts that do not put spaces between words —
it returns the whole phrase as one token. Those runs are indexed as overlapping
character **bigrams** instead, the strategy Lucene's CJKAnalyzer uses.
`analyzer.sql` does this automatically for:

| | ranges |
|---|---|
| Chinese | CJK unified, extension A, extension B, compatibility ideographs |
| Japanese | hiragana, katakana, katakana phonetic ext, **halfwidth katakana** |
| Korean | hangul syllables, hangul compatibility jamo |
| Thai, Lao, Khmer, Myanmar | full blocks |

Halfwidth katakana runs through U+FF9F rather than U+FF9D: the voiced sound marks are
separate characters, and stopping short of them splits `ﾊﾟﾝ` into two single-character
runs instead of the bigrams `ﾊﾟ ﾟﾝ`.

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

### What Postgres alone does with these scripts

For reference, this is why the bigram step exists — `to_tsvector` on its own
collapses a whole unspaced phrase into one unusable token:

```
to_tsvector('english', 'sourdough bread starter')
  -> 'bread':2 'sourdough':1 'starter':3          ✓ stemmed, stopworded

to_tsvector('english', '我想要一個關於酸種麵包的建議')
  -> '我想要一個關於酸種麵包的建議':1                  ✗ one token

to_tsvector('english', 'ขนมปังเปรี้ยว')
  -> 'ขนมปังเปรี้ยว':1                              ✗ one token
```

`bm25_terms` splits those runs out before calling `to_tsvector` and emits bigrams
for them, so both kinds of script are handled in one pass:

```
bm25_terms('ขนมปังเปรี้ยว')  -> ขน นม มป ปั ัง งเ เป ปร รี ี้ ้ย ยว
bm25_terms('I want 酸種麵包 recipes') -> want recip 酸種 種麵 麵包
```

## Index size scales with vocabulary, not corpus

`vchord_bm25` allocates roughly **8 KB per distinct vocabulary term**, largely
independent of how many documents contain it. **Vocabulary cardinality, not corpus
size, is what drives index size** — the single most important property to understand
about this design.

That makes chat and log data the pathological case, because it is full of tokens that
appear in exactly one document: snowflake ids, hashes, URLs, version strings. Each one
buys a permanent 8 KB posting list to match a single row.

`analyzer.sql` handles this by unmapping those token types from its text search
configuration. Postgres' parser already labels them (`uint`, `numword`, `url`,
`url_path`, `file`, `version`, …), so they are dropped by type rather than by
pattern-matching the output. Measured on 20,000 chat-shaped rows — usernames, Discord
channel URLs, snowflake ids, an MD5 per row:

| | vocabulary | BM25 index | database |
|---|---|---|---|
| `english` (stock configuration) | 81,714 terms | **641 MB** | 671 MB |
| `bm25_english` (this image) | 15 terms | **736 kB** | 15 MB |

That is 7.8 KB per term on the left, confirming the scaling law independently.

**The trade-off is explicit:** a bare number is no longer a searchable term, so
`SELECT … to_bm25_query('1084503117000007')` matches nothing. Numbers still appear in
stored content and still match by their surrounding words. If part numbers or versions
are the point of your corpus, put them back:

```sql
ALTER TEXT SEARCH CONFIGURATION public.bm25_english
  ADD MAPPING FOR uint, int WITH simple;
```

`host` and `email` are deliberately **kept** — both are low cardinality in practice and
people search for them.

**Residual:** plain-word tokens that occur once (an unusual surname, a typo) still cost
8 KB each. A document-frequency floor would need a second pass over the corpus, so it is
a maintenance job rather than something the write path can do. If the vocabulary grows
past a few hundred thousand rows, prune it and rebuild:

```sql
-- terms that appear in fewer than 2 documents, after the fact
DELETE FROM bm25_vocabulary v WHERE NOT EXISTS (
  SELECT 1 FROM messages m WHERE m.content ILIKE '%' || v.term || '%' LIMIT 2);
UPDATE messages SET content = content;   -- retrigger; then REINDEX
```

**Upgrading an existing database:** re-running `analyzer.sql` replaces the functions but
not the vectors already stored. Rows written under the old configuration keep their old
terms until rewritten — `UPDATE <table> SET content = content;` then `REINDEX INDEX
<table>_bm25_idx`.

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

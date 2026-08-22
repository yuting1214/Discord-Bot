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

| | version | |
|---|---|---|
| PostgreSQL | 18.6 | Railway `postgres-ssl` |
| pgvector | 0.8.6 | vector search |
| vchord_bm25 | 0.3.0 | BM25 ranking |
| icu_ext | 1.11.0 | word segmentation for Chinese, Thai, Khmer, Lao, Burmese |
| unaccent, pg_trgm, fuzzystrmatch, btree_gin | contrib | diacritics, typo tolerance |
| pgBackRest | 2.59.1 | Railway's backup tooling, retained |

All of them are **created for you on first boot**. A stock `postgres-ssl` has only
`plpgsql` enabled even though pgvector is already on disk, so every deployer's first
job is working out which `CREATE EXTENSION` statements to run. This one has run them
before you connect, and installed the analyzer with them.

### Configuration

| variable | default | |
|---|---|---|
| `SHARED_PRELOAD_LIBRARIES` | `vchord_bm25` | add your own preloaded extensions |
| `BM25_EXTENSIONS` | `vector,vchord_bm25,icu_ext,unaccent,pg_trgm,btree_gin,fuzzystrmatch` | `none` to skip |
| `BM25_ANALYZER` | `on` | `off` to skip the multilingual analyzer |

`SHARED_PRELOAD_LIBRARIES` matters more than it looks. A command-line `-c` **overrides
`postgresql.conf`**, and the image passes some — so a preload list written into
`postgresql.conf` is silently ignored, and without this variable no deployer could add a
preload-requiring extension at all without rebuilding the image.

Extensions and the analyzer are installed from `/docker-entrypoint-initdb.d`, which
Docker runs **only when the volume is empty**. On an existing database, apply
[`analyzer.sql`](analyzer.sql) by hand — it is idempotent.

## Memory

Idle anon memory, identical conditions, measured natively on arm64:

| configuration | idle |
|---|---|
| stock Railway `postgres-ssl` | 6.4 MB |
| **this image** | **6.7 MB** |
| + pg_tokenizer | 337.5 MB |

`pg_tokenizer` costs **~331 MB** and is deliberately **not** installed. `icu_ext` costs
0.2 MB and 273 kB on disk, because ICU is already linked into Postgres for collations.

> **Read this figure correctly.** 6.7 MB is *anon* memory at idle on an empty
> database. Total cgroup memory after a realistic 20,000-document workload is
> **87.6 MB**, against **95.4 MB** for the same workload on `pg_search`. The honest
> comparison against a BM25 competitor is roughly **8% better, not 50× better**.
> The 50× figure only describes the gap against `pg_tokenizer` at idle, which is an
> *allocation* penalty from preloading models — not a property of BM25 itself. BM25
> needs a `bm25vector` — a sparse `{term_id:frequency}` map — but nothing requires that
> vector to come from `pg_tokenizer`. Postgres' own text search produces the same thing
> for a rounding error in memory.

> Measure natively. On Apple Silicon, `--platform linux/amd64` runs under Rosetta
> and inflated every reading roughly 5× (6.4 MB read as 30.7 MB).

## Tokenizing without pg_tokenizer

[`analyzer.sql`](analyzer.sql) is applied for you on first boot. It is idempotent, so
applying it to an existing database is just:

```bash
psql "$DATABASE_URL" -f analyzer.sql
```

It creates a `bm25_vocabulary` table mapping terms to stable ids, and these functions:

| function | volatility | use |
|---|---|---|
| `bm25_script_class([script])` | IMMUTABLE | the character ranges of each unspaced script |
| `bm25_script_of(run)` | IMMUTABLE | which script a run belongs to |
| `bm25_runs(text)` | IMMUTABLE | the unspaced runs in a document, tagged by script |
| `bm25_words(run, locale)` | IMMUTABLE | ICU segmentation, or bigrams where ICU is absent |
| `bm25_terms(text)` | IMMUTABLE | **the tokenizer** — all three paths in one pass |
| `bm25_expand_term(term)` | STABLE | single-character CJK queries → the terms containing them |
| `bm25_nearest_term(term)` | STABLE | typo tolerance over the vocabulary, via `pg_trgm` |
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

### Languages

Postgres' text search cannot segment scripts that do not put spaces between words —
it returns the whole phrase as one token. `analyzer.sql` routes each script to the
tokenizer that handles it, **within a single document**:

| | segmenter | why |
|---|---|---|
| English, French, Spanish, Portuguese, German, Italian, Dutch, Russian, Arabic, Vietnamese, and 20 more | `to_tsvector` | stemming, stopwords; diacritics folded by `unaccent` |
| **Chinese** (unified, ext A, ext B, compatibility) | **ICU** | dictionary word segmentation |
| **Thai, Khmer, Lao, Burmese** | **ICU** | unspaced, and ICU has dictionaries for all four |
| **Japanese** (hiragana, katakana, halfwidth katakana, kanji) | bigrams | ICU shreds katakana compounds: サワードウ → `サワ｜ード｜ウ` |
| **Korean** (syllables, compatibility jamo) | bigrams | Korean glues particles to nouns (`빵에` = bread + locative); ICU leaves them attached, so a query for `빵` misses |

Han characters are Chinese *and* Japanese. If a document contains kana anywhere it is
Japanese and its kanji bigrams with the rest; otherwise it is Chinese and goes to ICU.

Two details that are easy to get wrong and silent when you do. Halfwidth katakana runs
through **U+FF9F**, not U+FF9D: the voiced sound marks are separate characters, and
stopping short of them splits `ﾊﾟﾝ` into singletons instead of the bigrams `ﾊﾟ ﾟﾝ`. And
the ranges are written as `\U` escapes rather than literal characters, because U+8C48
and U+F900 render identically — pasting the wrong one made the Han range swallow the
entire Hangul block, and Korean was quietly segmented as Chinese.

### Why not character unigrams

`pg_tokenizer`'s `unicode_segmentation` emits character **unigrams**, and individual
CJK characters are far too common to discriminate. Measured on a corpus with two
decoys containing 麵 and 包 non-adjacently, query `麵包` (bread):

| analyzer | rank 1 | rank 2 | rank 3 |
|---|---|---|---|
| pg_tokenizer (unigrams) | ✗ 這家**麵**店的**包**子 `-0.7409` | ✗ **包**裝這個**麵**條 `-0.7134` | ✓ 酸種**麵包** `-0.6418` |
| this image | ✓ 酸種**麵包** | `0.0000` | `0.0000` |

pg_tokenizer ranks **both decoys above the correct document**. Getting real word
segmentation out of it needs a Lindera model on top — more configuration, and more
memory again.

### Verifying this yourself

The relevance judgements are a data file, not prose. 13 locales, ranking plus
tokenization:

```bash
docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=pw postgres-bm25
uv run python -m bench.search_locales postgresql://postgres:pw@localhost:55432/postgres --reset
```

```
PASS  en            3 checks        PASS  th            3 checks
PASS  fr            2 checks        PASS  km            3 checks
PASS  vi            2 checks        PASS  lo            3 checks
PASS  zh-Hant       4 checks        PASS  my            2 checks
PASS  zh-Hans       3 checks        PASS  ru            3 checks
PASS  ja            3 checks        PASS  ar            3 checks
PASS  ko            3 checks        PASS  tokenization  22 checks

28 documents, 204 vocabulary terms, 1720 kB index
14/14 groups passed
```

Adding a language is an edit to [`bench/corpus.json`](../../bench/corpus.json).

### What ICU actually buys

Not speed. End to end it is **3–5× slower per document** than bigrams — a
microbenchmark of `icu_word_boundaries` on its own says the opposite, but that is not
what the analyzer does. The win is in the tokens. Same 28-document corpus, previous
bigram-only analyzer versus this one:

| | bigrams only | with ICU |
|---|---|---|
| vocabulary | 377 terms | **204 terms** |
| index | 3,104 kB | **1,720 kB** |
| Thai, one sentence | 37 tokens | **9 tokens** |
| Chinese, one sentence | 22 tokens | **14 tokens** |
| Lao decoy sharing no words | scores `-4.8806` ✗ | **`0.0000`** ✓ |
| Vietnamese typed without diacritics | no results ✗ | **ranks correctly** ✓ |
| Korean single-character query `빵` | no results ✗ | **ranks correctly** ✓ |

Since vchord_bm25 spends ~8 kB of index per distinct term, **fewer and better terms is
what costs less** — the 45% smaller index above is the same fact as the better ranking.

Tokenizer cost per document, best of five runs of 3,000 iterations:

| | bigrams only | with ICU |
|---|---|---|
| English | 0.0192 ms | 0.0187 ms |
| Chinese | 0.0270 ms | 0.0990 ms |
| Japanese | 0.0268 ms | 0.0856 ms |
| Korean | 0.0327 ms | 0.1134 ms |
| Thai | 0.0206 ms | 0.1087 ms |

English is unaffected because documents with no unspaced script never enter the
segmenter at all. For the rest, a tenth of a millisecond against a ~6 ms search is not
where the time goes.

### Against pg_tokenizer

20,000 mixed English/Chinese documents, identical corpus and queries, native arm64:

| | pg_tokenizer | this image |
|---|---|---|
| idle memory | 336.6 MB | **6.7 MB** |
| after workload | 336.9 MB | **6.8 MB** |
| ingest 20k docs | **3.5 s** | 12.3 s |
| index build | **368 ms** | 418 ms |
| search, 200 varying queries | **0.37 ms** each | 6.5 ms each |
| CJK precision | ✗ decoys outrank | ✓ correct |

pg_tokenizer is genuinely faster — roughly 17× per search and 3.5× on ingest. The
trade is 330 MB of permanently resident memory and worse CJK ranking. At 6.5 ms a
search this is not a bottleneck for a chat application, and the memory is the
difference between a database service that is cheap to leave running and one that is
not. If your workload is high-QPS search where 6 ms matters more than 330 MB, install
pg_tokenizer and configure a Lindera model for CJK.

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

## Recipes

Everything below is SQL against the schema above — nothing to install, and every
snippet here was run against this image before being written down.

### Hybrid search: BM25 and vectors in one query

The argument for keeping search in your database rather than beside it. Fuse the two
rankings by **rank**, not by score — cosine similarity lands around 0.3–0.5 while BM25
scores are unbounded negatives, so any weighted sum of the raw numbers is really just
one of the two tiers wearing a hat.

```sql
SET search_path TO public, bm25_catalog;

WITH lexical AS (
  SELECT id, row_number() OVER (
           ORDER BY bm25 <&> bm25_catalog.to_bm25query(
             'messages_bm25_idx', public.to_bm25_query('sourdough starter'))) AS rank
  FROM messages ORDER BY rank LIMIT 20
), semantic AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> $1) AS rank
  FROM messages ORDER BY rank LIMIT 20
)
SELECT m.content,
       COALESCE(1.0/(60 + l.rank), 0) + COALESCE(1.0/(60 + s.rank), 0) AS rrf
FROM lexical l
FULL JOIN semantic s USING (id)
JOIN messages m USING (id)
ORDER BY rrf DESC
LIMIT 10;
```

`60` is the standard RRF constant; raise it to flatten the contribution of top ranks.
Weight a tier by multiplying its term. `FULL JOIN` matters — a document found by only
one tier must still appear, which is the whole point of running both.

The two fail in different ways, which is why both exist. On real data a content-free
message (`"you good?"`) scored **exactly 0.0000** for an unrelated query on the BM25
tier, where embedding search ranked it *above* a genuinely relevant row.

### Faceting

ParadeDB sells faceted search as a feature. In SQL it is an aggregate, and it costs
one pass rather than one query per facet:

```sql
WITH hits AS (
  SELECT locale, created_at,
         bm25 <&> bm25_catalog.to_bm25query(
           'messages_bm25_idx', public.to_bm25_query('bread starter')) AS score
  FROM messages)
SELECT count(*) FILTER (WHERE score < 0)                        AS matching,
       count(*) FILTER (WHERE score < 0 AND locale = 'en')      AS english,
       count(*) FILTER (WHERE score < 0
                        AND created_at > now() - interval '7 days') AS this_week
FROM hits;
```

A score of exactly `0` means no term in common — that is the "no match" test, not a
threshold you have to tune. `GROUPING SETS` gives you several facet dimensions at once.

### Typo tolerance

An unknown query term matches nothing, which is correct BM25 and unforgiving.
`bm25_nearest_term` rewrites it to the closest term the corpus actually contains,
using a trigram index over the vocabulary:

```sql
SELECT public.bm25_nearest_term('sourdogh');   -- sourdough
SELECT public.bm25_nearest_term('hydraton');   -- hydrat  (the stem, which is the term)
SELECT public.bm25_nearest_term('sourdough');  -- sourdough, unchanged
```

It matches against the **vocabulary**, so it can only ever suggest a word that is in
your data. Raise the second argument (default `0.4`) to be stricter.

### Highlighting

`ts_headline` marks matched words in a result, and on its own it cannot mark any of the
scripts this image exists for. It re-parses the document with the configuration's
parser, which does not segment them — so a search that ranked a Chinese document
correctly hands it back with nothing marked, which reads as a broken search box.

`bm25_headline` runs `ts_headline` for the spaced part and locates the analyzer's own
terms for the rest:

| query | `ts_headline` | `bm25_headline` |
|---|---|---|
| `sourdough` | looking for **sourdough** bread starter | looking for **sourdough** bread starter |
| `麵包` | 酸種麵包的做法其實很簡單 ✗ | 酸種**麵包**的做法其實很簡單 ✓ |
| `ขนมปัง` | …เกี่ยวกับขนมปังเปรี้ยว ✗ | …เกี่ยวกับ**ขนมปัง**เปรี้ยว ✓ |
| `빵` | 사워도우 빵에 대한 ✗ | 사워도우 **빵**에 대한 ✓ |

```sql
SELECT public.bm25_headline(content, 'sourdough hydration', '<mark>', '</mark>')
FROM messages
ORDER BY bm25 <&> bm25_catalog.to_bm25query(
           'messages_bm25_idx', public.to_bm25_query('sourdough hydration'))
LIMIT 5;
```

Selectors default to `<b>`/`</b>`. It marks only terms that are genuinely in the
document, so a decoy that ranked below the target comes back with nothing marked —
which is the honest thing for a snippet to show. Japanese and Korean are bigram-marked
and adjacent spans are spliced together, so `サワードウ` marks as `**サワード**ウ`
rather than four separate fragments: contiguous, and one character short of the full
compound, because the last bigram overlaps the one before it.

### Phrase, proximity and boolean search

A `bm25vector` is a bag of `{term_id:frequency}` — it has **no positions**, so BM25
alone cannot answer "these two words, in this order". Add a generated `tsvector`
alongside it. The two coexist: BM25 ranks, `tsvector` filters.

```sql
ALTER TABLE messages ADD COLUMN ts tsvector
  GENERATED ALWAYS AS (to_tsvector('public.bm25_english', content)) STORED;
CREATE INDEX messages_ts_idx ON messages USING gin (ts);
```

```sql
-- exact phrase
WHERE ts @@ phraseto_tsquery('public.bm25_english', 'sourdough bread')
-- within N words
WHERE ts @@ to_tsquery('public.bm25_english', 'starter <3> four')
-- Google-style: quotes, or, and leading minus
WHERE ts @@ websearch_to_tsquery('public.bm25_english', '"bread starter" or hydration -rye')
```

The generated column is free to keep correct and costs one GIN index. It uses the same
configuration as BM25, so stemming, stopwords and diacritic folding agree between the
two. **Caveat:** `to_tsvector` does not segment unspaced scripts, so phrase search does
not work for Chinese, Japanese, Korean, Thai, Khmer, Lao or Burmese. For those, bigram
adjacency already approximates phrase matching — a two-character query *is* a phrase.

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

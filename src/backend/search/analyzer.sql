-- BM25 text analysis without pg_tokenizer.
--
-- VENDORED. The canonical copy, its 13-locale verification corpus and the
-- benchmarks behind every number quoted below live in:
--
--     https://github.com/yuting1214/postgres-search
--
-- It is duplicated here because the application container ships src/ and
-- nothing else, and the bot applies this file at startup (see init_db). Fix
-- bugs there and copy the file across; do not diverge.
--
-- A bm25vector is a sparse {term_id:frequency} map. Nothing requires those ids
-- to come from pg_tokenizer, which costs ~331MB of resident memory because it
-- preloads tokenizer models. This produces the same vectors from Postgres' own
-- text search, ICU, and bigrams, at ~0.3MB.
--
-- Three tokenizers, chosen per script within a single document:
--
--   spaced scripts        to_tsvector  -- stemming, stopwords, diacritic folding
--   zh, th, km, lo, my    icu_ext      -- real dictionary word segmentation
--   ja, ko                bigrams      -- overlapping character pairs
--
-- ICU is used where its dictionaries are good and skipped where they are not.
-- It segments Chinese, Thai, Khmer, Lao and Burmese correctly, where bigrams
-- only approximate word boundaries -- but it shreds Japanese katakana compounds
-- and leaves Korean particles attached to their nouns, so a query for 빵 would
-- miss a document containing 빵에. Bigrams -- the strategy Lucene's CJKAnalyzer
-- uses -- recover both.
--
-- ICU is not the faster path, whatever a microbenchmark of icu_word_boundaries
-- against this file suggests: end to end it is 3-5x slower per document,
-- because the win is in the tokens, not the clock. Thai goes from 37 tokens to
-- 9 and Chinese from 22 to 14 on the same sentences, and since vchord_bm25
-- spends ~8KB of index per distinct term, fewer and better terms is what
-- actually costs less.
--
-- Without icu_ext installed everything falls back to bigrams, so the analyzer
-- still works against a stock PostgreSQL. Character unigrams -- what
-- pg_tokenizer's unicode_segmentation produces -- are never used: individual
-- characters are far too common to discriminate, and rank decoys above the
-- correct document.
--
-- Idempotent: safe to run on every start.

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
-- vchord_bm25 forces its own schema, bm25_catalog, and rejects WITH SCHEMA.
CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;

-- Optional. Each is skipped rather than fatal, so this script also applies to a
-- database that is not running our image.
DO $do$
DECLARE ext text;
BEGIN
    FOREACH ext IN ARRAY ARRAY['icu_ext', 'unaccent', 'pg_trgm'] LOOP
        IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = ext) THEN
            -- WITH SCHEMA public, not wherever the caller's search_path
            -- happens to point: every reference below is public-qualified, so
            -- an extension that lands anywhere else is invisible to them.
            EXECUTE format('CREATE EXTENSION IF NOT EXISTS %I WITH SCHEMA public', ext);
        ELSE
            RAISE NOTICE 'bm25: % not available, degrading', ext;
        END IF;
    END LOOP;
END $do$;

-- ---------------------------------------------------------------------------
-- Text search configuration
-- ---------------------------------------------------------------------------
-- vchord_bm25 allocates roughly 8KB of index per distinct term id, near enough
-- independently of how many documents contain it. Vocabulary cardinality, not
-- corpus size, is therefore what drives index size: 20,000 chat-shaped rows
-- measured a 641MB index under the stock `english` configuration and 736kB
-- under this one.
--
-- The difference is entirely ids, hashes, URLs and version strings, each of
-- which would buy a permanent 8KB posting list to match a single row. Postgres'
-- parser already labels them, so they are dropped by token type rather than by
-- pattern-matching the tokenizer's output.
--
-- To index them anyway (a corpus where part numbers or versions are the point):
--   ALTER TEXT SEARCH CONFIGURATION public.bm25_english
--     ADD MAPPING FOR uint, int WITH simple;
DO $do$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace
        WHERE c.cfgname = 'bm25_english' AND n.nspname = 'public'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION public.bm25_english (COPY = pg_catalog.english);
    END IF;
END $do$;

-- host and email are kept: both are low cardinality in practice and are things
-- people actually search for. url_path and file are not.
ALTER TEXT SEARCH CONFIGURATION public.bm25_english DROP MAPPING IF EXISTS FOR
    numword, numhword, hword_numpart,
    int, uint, float, sfloat, version,
    url, url_path, file,
    tag, entity;

-- Fold diacritics at index time so cafe finds café. Not cosmetic: Vietnamese is
-- routinely typed without diacritics, and without this those queries return
-- nothing at all.
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'unaccent') THEN
        ALTER TEXT SEARCH CONFIGURATION public.bm25_english
            ALTER MAPPING FOR asciiword, word, hword, hword_part,
                              asciihword, hword_asciipart
            WITH unaccent, english_stem;
    END IF;
END $do$;

-- ---------------------------------------------------------------------------
-- Vocabulary
-- ---------------------------------------------------------------------------
-- Schema-qualified like everything else here. Unqualified, it lands in
-- whatever schema happens to be first on the caller's search_path, while every
-- function below looks for it in public -- so the two disagree the moment
-- anyone runs with a different path.
CREATE TABLE IF NOT EXISTS public.bm25_vocabulary (
    id   serial PRIMARY KEY,
    term text UNIQUE NOT NULL
);

-- Every search joins against this table, and the plan it gets depends entirely
-- on having current statistics for it: with none, the planner abandons index
-- lookups on term for a full scan and the same query costs 85 ms instead of
-- 1.2 ms. Autovacuum's default analyzes after 10% of the table changes, so on
-- a vocabulary growing into the hundreds of thousands the stale window gets
-- *longer* as the corpus grows -- exactly backwards.
--
-- A flat threshold with no scale factor analyzes after roughly every 1,000 new
-- terms whatever the size. On a table this narrow that is cheap, and it turns
-- "ANALYZE after a bulk load" from something a deployer must remember into
-- something the database does.
ALTER TABLE public.bm25_vocabulary SET (
    autovacuum_analyze_scale_factor = 0.0,
    autovacuum_analyze_threshold    = 1000
);

-- ---------------------------------------------------------------------------
-- Scripts
-- ---------------------------------------------------------------------------
-- Character ranges for the scripts to_tsvector cannot segment, written in one
-- place because a write path and a read path that disagree about them would
-- silently stop those documents matching.
--
--   han     3400-4DBF   extension A      4E00-9FFF   unified
--           F900-FAFF   compatibility    20000-2A6DF extension B
--   kana    3041-30FF   hiragana + katakana
--           31F0-31FF   phonetic extensions
--           FF66-FF9F   halfwidth -- through FF9F, because the voiced sound
--                       marks are separate characters and stopping at FF9D
--                       splits a run into singletons
--   hangul  AC00-D7A3   syllables        3130-318F   compatibility jamo
--   th      0E01-0E5B   km  1780-17FF    lo  0E81-0EDF    my  1000-109F
--
-- Written as \U escapes, never as literal characters. U+8C48 and U+F900 are
-- different codepoints that render identically, and pasting the wrong one made
-- the han range U+8C48-U+FAFF -- which swallows the whole Hangul block, so
-- Korean was silently routed through the Chinese segmenter.
CREATE OR REPLACE FUNCTION public.bm25_script_class(script text DEFAULT 'all')
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE script
        WHEN 'han'    THEN '[\U00003400-\U00004DBF\U00004E00-\U00009FFF'
                        || '\U0000F900-\U0000FAFF\U00020000-\U0002A6DF]'
        WHEN 'kana'   THEN '[\U00003041-\U000030FF\U000031F0-\U000031FF\U0000FF66-\U0000FF9F]'
        WHEN 'hangul' THEN '[\U0000AC00-\U0000D7A3\U00003130-\U0000318F]'
        WHEN 'th'     THEN '[\U00000E01-\U00000E5B]'
        WHEN 'km'     THEN '[\U00001780-\U000017FF]'
        WHEN 'lo'     THEN '[\U00000E81-\U00000EDF]'
        WHEN 'my'     THEN '[\U00001000-\U0000109F]'
        ELSE '[\U00003400-\U00004DBF\U00004E00-\U00009FFF\U0000F900-\U0000FAFF'
          || '\U00020000-\U0002A6DF\U00003041-\U000030FF\U000031F0-\U000031FF'
          || '\U0000FF66-\U0000FF9F\U0000AC00-\U0000D7A3\U00003130-\U0000318F'
          || '\U00000E01-\U00000E5B\U00001780-\U000017FF\U00000E81-\U00000EDF'
          || '\U00001000-\U0000109F]'
    END;
$$;

-- Which of them a run belongs to, decided on its first character. Classifying
-- the run rather than extracting one run per script is what keeps this to a
-- single pass over the document: seven passes cost more than ICU saves, and
-- they cost it on every document including the ones with no unspaced script in
-- them at all.
--
-- A run that mixes scripts is classified by the script it starts with. That is
-- exactly right for the case that matters -- Japanese interleaves kanji and
-- kana constantly, and the whole run wants bigrams either way.
CREATE OR REPLACE FUNCTION public.bm25_script_of(run text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN c ~ public.bm25_script_class('kana')   THEN 'kana'
        WHEN c ~ public.bm25_script_class('hangul') THEN 'hangul'
        WHEN c ~ public.bm25_script_class('th')     THEN 'th'
        WHEN c ~ public.bm25_script_class('km')     THEN 'km'
        WHEN c ~ public.bm25_script_class('lo')     THEN 'lo'
        WHEN c ~ public.bm25_script_class('my')     THEN 'my'
        ELSE 'han'
    END
    FROM (SELECT left(run, 1)) AS f(c);
$$;

-- ROWS on every set-returning function below is load-bearing, not decoration.
-- Postgres assumes 1000 rows from a set-returning function that does not say
-- otherwise, and to_bm25_query joins one of them against bm25_vocabulary: at
-- 1000 estimated query terms the planner stops looking terms up in
-- vocabulary.term and starts scanning the whole table and filtering, which is
-- O(vocabulary) per search. Measured on 50,000 documents with a 20,000-term
-- vocabulary: 85 ms per to_bm25_query call without these, 0.35 ms with them,
-- and 914 ms vs 1.6 ms for the top-10 query around it. Deep pagination went
-- from 9.8 s to 3.4 ms and a matching-document count from >60 s to 392 ms.
-- The defect is invisible on a small vocabulary, which is why it survived the
-- benchmarks: they use a 33-term corpus.
CREATE OR REPLACE FUNCTION public.bm25_runs(content text)
RETURNS TABLE(script text, run text) LANGUAGE sql IMMUTABLE PARALLEL SAFE ROWS 4 AS $$
    SELECT public.bm25_script_of(m.run), m.run
    FROM (SELECT (regexp_matches(content, public.bm25_script_class() || '+', 'g'))[1]) AS m(run);
$$;

-- ---------------------------------------------------------------------------
-- Segmenters
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.bm25_bigrams(run text)
RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE ROWS 20 AS $$
    -- A lone character indexes as itself, so single-character queries match.
    SELECT CASE WHEN length(run) = 1 THEN run ELSE substr(run, i, 2) END
    FROM generate_series(1, GREATEST(length(run) - 1, 1)) AS i;
$$;

-- Defined against whichever of the two is possible here. icu_word_boundaries is
-- declared VOLATILE upstream; the wrapper asserts IMMUTABLE on the same grounds
-- to_tsvector does -- deterministic for a given input, with results that change
-- only when the underlying data does, and a reindex is the answer either way.
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'icu_ext') THEN
        EXECUTE $f$
            CREATE OR REPLACE FUNCTION public.bm25_words(run text, locale text)
            RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE ROWS 20 AS $body$
                -- tag 0 is punctuation and whitespace; everything else is a word.
                SELECT lower(w.contents)
                FROM public.icu_word_boundaries(run, locale) w
                WHERE w.tag <> 0;
            $body$;
        $f$;
    ELSE
        EXECUTE $f$
            CREATE OR REPLACE FUNCTION public.bm25_words(run text, locale text)
            RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE ROWS 20 AS $body$
                SELECT public.bm25_bigrams(run);
            $body$;
        $f$;
    END IF;
END $do$;

-- Every token from every unspaced run in one document, in one call.
--
-- Han is the ambiguous case: the same characters are Chinese and Japanese. If
-- the document contains kana anywhere it is Japanese, and its kanji goes to
-- bigrams with the rest of it; otherwise it is Chinese and goes to ICU.
--
-- Per *document*, not per run, and that is the whole point. A set-returning SQL
-- function costs roughly 0.004 ms per invocation to set up, which is nothing
-- until you call it once per run -- and a Korean sentence is five runs, a
-- Japanese one a dozen. Dispatching per run measured 4.8x the bigram-only cost
-- on Korean, which uses no ICU at all and should have been free. The CTE is
-- referenced by both branches, so the run extraction still happens only once.
CREATE OR REPLACE FUNCTION public.bm25_unspaced_terms(content text)
RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE ROWS 40 AS $$
    WITH r AS (
        SELECT public.bm25_script_of(m.run) AS script,
               m.run,
               content ~ public.bm25_script_class('kana') AS japanese
        FROM (SELECT (regexp_matches(
                  content, public.bm25_script_class() || '+', 'g'))[1]) AS m(run)
    )
    SELECT CASE WHEN length(r.run) = 1 THEN r.run ELSE substr(r.run, i, 2) END
    FROM r, LATERAL generate_series(1, GREATEST(length(r.run) - 1, 1)) AS i
    WHERE r.script IN ('kana', 'hangul') OR (r.script = 'han' AND r.japanese)
    UNION ALL
    SELECT w.token
    FROM r, LATERAL public.bm25_words(
             r.run, CASE WHEN r.script = 'han' THEN 'zh' ELSE r.script END) AS w(token)
    WHERE r.script IN ('th', 'km', 'lo', 'my') OR (r.script = 'han' AND NOT r.japanese);
$$;

-- ---------------------------------------------------------------------------
-- Tokenizer
-- ---------------------------------------------------------------------------
-- Every identifier is schema-qualified. A SQL function resolves types against
-- the caller's search_path when it is inlined, so an unqualified bm25vector
-- fails for any caller that has not put bm25_catalog on its path.
CREATE OR REPLACE FUNCTION public.bm25_terms(
    content text,
    cfg regconfig DEFAULT 'public.bm25_english'
)
RETURNS TABLE(term text) LANGUAGE sql IMMUTABLE PARALLEL SAFE ROWS 40 AS $$
    -- Spaced scripts: unspaced runs are blanked out first so they do not become
    -- one huge token. Most documents have none, and the CASE keeps those off
    -- the rewrite entirely -- a plain regexp_replace over every document cost
    -- more than the whole ICU path saves.
    SELECT lexeme
    FROM unnest(to_tsvector(cfg,
        CASE WHEN content ~ public.bm25_script_class()
             THEN regexp_replace(content, public.bm25_script_class() || '+', ' ', 'g')
             ELSE content END))
    -- A term longer than this is a base64 blob or a stack frame, never a word,
    -- and would cost the same 8KB of index as a real one.
    WHERE length(lexeme) <= 64
    UNION ALL
    -- The guard is not redundant with the function's own regexp: without it the
    -- set-returning call is still set up and torn down for every document, and
    -- most documents have no unspaced script in them at all.
    SELECT public.bm25_unspaced_terms(content)
    WHERE content ~ public.bm25_script_class();
$$;

-- Register every term of a batch of documents in one ordered statement.
--
-- REQUIRED BEFORE CONCURRENT BULK INGEST. Without it, parallel writers
-- deadlock on the vocabulary almost totally: 8 writers x 10 batches x 200 rows
-- measured 79 deadlocks and 200 of 16,000 rows committed, at 3 rows/s. Calling
-- this first: 0 deadlocks, 16,000 of 16,000 rows, 7,076 rows/s.
--
-- The mechanism is not obvious. INSERT .. ON CONFLICT DO NOTHING must wait on
-- a concurrent *uncommitted* inserter of the same key, and to_bm25 registers
-- terms once per row -- so a 200-document transaction issues 200 separate
-- vocabulary INSERTs, and two transactions acquire overlapping terms in
-- unrelated orders and form a cycle. Ordering the terms inside to_bm25 does
-- not help and was measured not to: the statements are what is unordered, not
-- the rows within one. Collapsing a whole batch into a single ORDER BY-ed
-- statement makes every transaction take vocabulary keys in the same order,
-- which is what removes the cycle.
--
--   SELECT public.bm25_register(ARRAY[...]);   -- then INSERT the rows
--
-- Idempotent, and safe to call for documents already registered. Committing it
-- in its own transaction before inserting the rows is faster still (11,098
-- rows/s) at the cost of leaving terms behind if the batch then rolls back --
-- harmless, since the vocabulary is append-only either way.
CREATE OR REPLACE FUNCTION public.bm25_register(
    contents text[],
    cfg regconfig DEFAULT 'public.bm25_english'
)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE registered bigint;
BEGIN
    -- NOT EXISTS before ON CONFLICT: see to_bm25. Registering a batch whose
    -- terms are already known should cost no sequence values at all, and
    -- without this it costs one per term per call.
    INSERT INTO public.bm25_vocabulary (term)
    SELECT d.term
    FROM (SELECT DISTINCT t.term
          FROM unnest(contents) AS c(content),
               LATERAL public.bm25_terms(c.content, cfg) AS t(term)) d
    WHERE NOT EXISTS (SELECT 1 FROM public.bm25_vocabulary v WHERE v.term = d.term)
    ORDER BY 1
    ON CONFLICT (term) DO NOTHING;
    GET DIAGNOSTICS registered = ROW_COUNT;
    RETURN registered;
END $$;

-- Write path: VOLATILE, because it extends the vocabulary with unseen terms.
--
-- Single-row and low-concurrency ingest can use this on its own via the
-- trigger. Concurrent batch writers must call bm25_register first -- see above.
CREATE OR REPLACE FUNCTION public.to_bm25(
    content text,
    cfg regconfig DEFAULT 'public.bm25_english'
)
RETURNS bm25_catalog.bm25vector LANGUAGE plpgsql AS $$
DECLARE
    result bm25_catalog.bm25vector;
    terms  text[];
BEGIN
    -- Tokenize once. An earlier version called bm25_terms twice -- once to
    -- extend the vocabulary and again to count frequencies -- which is the
    -- expensive half of the write path paid twice per document, and
    -- tokenization is what dominates ingest.
    --
    -- Held in an array rather than folded into one statement with a
    -- data-modifying CTE, deliberately: rows inserted by a CTE are not visible
    -- to the rest of the same statement, so the frequency join would silently
    -- miss every newly registered term. Two statements means the second takes
    -- a fresh snapshot and sees both our own inserts and any a concurrent
    -- writer committed in between.
    SELECT array_agg(term) INTO terms FROM public.bm25_terms(content, cfg);

    IF terms IS NULL THEN
        RETURN '{}'::bm25_catalog.bm25vector;
    END IF;

    -- The NOT EXISTS is not redundant with ON CONFLICT. `serial` takes its
    -- default before the conflict is detected, so ON CONFLICT DO NOTHING burns
    -- a sequence value for every term that already existed -- and in steady
    -- state almost every term already exists. Measured on real prose that cost
    -- 49.7 ids per document against a vocabulary growing by far less, which
    -- exhausts the int4 sequence at ~43M documents.
    --
    -- ON CONFLICT stays as the backstop: two transactions can both pass the
    -- NOT EXISTS and only one can win the unique index.
    INSERT INTO public.bm25_vocabulary (term)
    SELECT u FROM (SELECT DISTINCT unnest(terms) AS u) d
    WHERE NOT EXISTS (SELECT 1 FROM public.bm25_vocabulary v WHERE v.term = d.u)
    ORDER BY 1
    ON CONFLICT (term) DO NOTHING;

    -- Term ids must ascend; the type rejects unsorted input.
    SELECT COALESCE('{' || string_agg(v.id || ':' || t.freq, ', ' ORDER BY v.id) || '}', '{}')
             ::bm25_catalog.bm25vector
    INTO result
    FROM (SELECT u AS term, count(*) AS freq
          FROM unnest(terms) AS u GROUP BY u) t
    JOIN public.bm25_vocabulary v ON v.term = t.term;
    RETURN result;
END $$;

-- A single-character query in a segmented script is a real word -- 빵 (bread),
-- 麵 (noodle) -- but it is almost never a term, because the document that
-- contains it was segmented into 빵에 or 麵包. Without this, those queries
-- return nothing at all. Expanded to the short vocabulary terms containing that
-- character, capped so an unlucky common character cannot turn one query term
-- into hundreds.
-- ROWS 2, not the default 1000: this returns the term itself for everything
-- except a single-character CJK query, and the estimate is what decides whether
-- to_bm25_query looks terms up in bm25_vocabulary or scans all of it.
CREATE OR REPLACE FUNCTION public.bm25_expand_term(t text, cap int DEFAULT 16)
RETURNS SETOF text LANGUAGE sql STABLE PARALLEL SAFE ROWS 2 AS $$
    SELECT t
    WHERE length(t) > 1
       OR t !~ public.bm25_script_class()
       OR EXISTS (SELECT 1 FROM public.bm25_vocabulary v WHERE v.term = t)
    UNION ALL
    SELECT term FROM (
        SELECT v.term FROM public.bm25_vocabulary v
        WHERE length(t) = 1
          AND t ~ public.bm25_script_class()
          AND NOT EXISTS (SELECT 1 FROM public.bm25_vocabulary w WHERE w.term = t)
          AND length(v.term) BETWEEN 2 AND 3
          AND position(t IN v.term) > 0
        ORDER BY length(v.term), v.id
        LIMIT cap
    ) e;
$$;

-- Read path: STABLE and non-writing. A read that writes is VOLATILE, and the
-- planner then re-evaluates it once per row instead of once per query -- which
-- measured 106ms per search instead of 6.5ms. Unknown query terms simply match
-- nothing, which is correct BM25 behaviour.
CREATE OR REPLACE FUNCTION public.to_bm25_query(
    content text,
    cfg regconfig DEFAULT 'public.bm25_english'
)
RETURNS bm25_catalog.bm25vector LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT COALESCE('{' || string_agg(v.id || ':' || t.freq, ', ' ORDER BY v.id) || '}', '{}')
             ::bm25_catalog.bm25vector
    FROM (SELECT e.term, count(*) AS freq
          FROM public.bm25_terms(content, cfg) raw,
               LATERAL public.bm25_expand_term(raw.term) AS e(term)
          GROUP BY e.term) t
    JOIN public.bm25_vocabulary v ON v.term = t.term;
$$;

-- Typo tolerance. An unknown query term matches nothing, which is correct and
-- unforgiving; this rewrites it to the closest term the corpus actually
-- contains before the vector is built.
DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS bm25_vocabulary_trgm
            ON public.bm25_vocabulary USING gin (term public.gin_trgm_ops);

        EXECUTE $f$
            CREATE OR REPLACE FUNCTION public.bm25_nearest_term(t text, threshold real DEFAULT 0.4)
            RETURNS text LANGUAGE sql STABLE PARALLEL SAFE AS $body$
                SELECT COALESCE(
                    -- Exact hit first, on the unique index. Without this every
                    -- correctly spelled term still pays for a trigram scan,
                    -- and a fuzzy query is mostly correctly spelled terms.
                    (SELECT t WHERE EXISTS (
                        SELECT 1 FROM public.bm25_vocabulary v WHERE v.term = t)),
                    (SELECT v.term FROM public.bm25_vocabulary v
                     WHERE v.term % t AND public.similarity(v.term, t) >= threshold
                     ORDER BY public.similarity(v.term, t) DESC LIMIT 1),
                    t);
            $body$;
        $f$;

        -- Read path with typo correction.
        --
        -- to_bm25_query on its own is unforgiving by design: a term not in the
        -- vocabulary matches nothing, which is correct BM25 and useless in a
        -- search box. This corrects each term to the nearest one the corpus
        -- actually contains before building the vector.
        --
        -- It corrects *terms*, not the query text, and that is the whole
        -- difficulty. bm25_terms emits stems -- the vocabulary holds `hydrat`
        -- and `advic`, never `hydration` and `advice` -- so the obvious
        -- composition, correcting words and calling to_bm25_query on the
        -- result, would push already-stemmed text back through the stemmer.
        -- Building the vector directly from corrected terms skips that second
        -- pass, which is why this is a separate function rather than a wrapper.
        EXECUTE $f$
            CREATE OR REPLACE FUNCTION public.to_bm25_query_fuzzy(
                content   text,
                threshold real DEFAULT 0.4,
                cfg       regconfig DEFAULT 'public.bm25_english'
            )
            RETURNS bm25_catalog.bm25vector LANGUAGE sql STABLE PARALLEL SAFE AS $body$
                SELECT COALESCE('{' || string_agg(v.id || ':' || t.freq, ', ' ORDER BY v.id) || '}', '{}')
                         ::bm25_catalog.bm25vector
                FROM (SELECT e.term, count(*) AS freq
                      FROM public.bm25_terms(content, cfg) raw,
                           LATERAL public.bm25_expand_term(
                               public.bm25_nearest_term(raw.term, threshold)) AS e(term)
                      GROUP BY e.term) t
                JOIN public.bm25_vocabulary v ON v.term = t.term;
            $body$;
        $f$;
    END IF;
END $do$;

-- ---------------------------------------------------------------------------
-- Vocabulary maintenance
-- ---------------------------------------------------------------------------
-- The vocabulary is append-only: nothing removes a term when the document that
-- introduced it is deleted, and DROP TABLE reclaims none of it. Since
-- vchord_bm25 spends ~8KB of index per distinct term, terms that no longer
-- appear anywhere are pure cost.
--
-- Document frequency is read from the stored vectors, not from the text. A
-- bm25vector prints as {term_id:frequency, ...} and lists each term once, so
-- counting ids across the table gives an exact document frequency in one pass.
-- 50,000 documents over a 20,000-term vocabulary: 643 ms.
--
-- The obvious alternative -- matching each vocabulary term against the document
-- text with ILIKE -- is O(vocabulary x corpus), needs an index it cannot use,
-- and is wrong anyway: it matches substrings rather than terms, so 'rye' counts
-- every occurrence of 'rye' inside 'wrye'.
-- Every table carrying a bm25vector column, found from the catalogue.
--
-- The vocabulary is one namespace shared by the whole database, and that is
-- deliberate. Measured on two tables with disjoint vocabularies: results stay
-- completely separate -- querying one for a term only the other contains
-- returns nothing -- and index allocation tracks the distinct terms actually
-- present rather than the highest id, so sharing costs neither correctness nor
-- space. Scoping the vocabulary per index would buy isolation that already
-- exists where it matters.
--
-- What sharing does cost is that pruning is a whole-database operation. Prune
-- while some table still uses a term and that table keeps the term in its
-- stored vectors but can no longer resolve it, so it silently stops matching.
-- Asking the catalogue rather than the caller is what makes the safe thing the
-- default.
CREATE OR REPLACE FUNCTION public.bm25_indexed_columns()
RETURNS TABLE(tbl regclass, col name) LANGUAGE sql STABLE ROWS 4 AS $$
    SELECT a.attrelid::regclass, a.attname
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    WHERE a.atttypid = 'bm25_catalog.bm25vector'::regtype
      AND NOT a.attisdropped
      AND a.attnum > 0
      AND c.relkind IN ('r', 'p', 'm')
    ORDER BY 1, 2;
$$;

-- Document frequency for every vocabulary term.
--
-- With no arguments this covers every bm25vector column in the database, which
-- is the only safe default: a term is dead only if nothing anywhere uses it.
-- Pass an explicit list to scope it deliberately.
CREATE OR REPLACE FUNCTION public.bm25_vocabulary_usage(
    tables regclass[] DEFAULT NULL,
    col name DEFAULT NULL
)
RETURNS TABLE(id int, term text, df bigint) LANGUAGE plpgsql STABLE AS $$
DECLARE r record; parts text[] := '{}';
BEGIN
    IF tables IS NULL THEN
        FOR r IN SELECT * FROM public.bm25_indexed_columns() LOOP
            parts := parts || format(
                'SELECT (m[1])::int AS tid FROM %s d, '
                'LATERAL regexp_matches(d.%I::text, $re$(\d+):(\d+)$re$, $g$g$g$) m',
                r.tbl, r.col);
        END LOOP;
    ELSE
        FOR r IN SELECT t AS tbl, COALESCE(col, 'bm25')::name AS col
                 FROM unnest(tables) AS t LOOP
            parts := parts || format(
                'SELECT (m[1])::int AS tid FROM %s d, '
                'LATERAL regexp_matches(d.%I::text, $re$(\d+):(\d+)$re$, $g$g$g$) m',
                r.tbl, r.col);
        END LOOP;
    END IF;

    -- No bm25vector column anywhere means no evidence either way, and reporting
    -- every term as unused would let a prune wipe the whole vocabulary.
    IF cardinality(parts) = 0 THEN
        RAISE EXCEPTION 'bm25_vocabulary_usage: no bm25vector columns found';
    END IF;

    RETURN QUERY EXECUTE format($q$
        SELECT v.id, v.term, COALESCE(u.df, 0)
        FROM public.bm25_vocabulary v
        LEFT JOIN (SELECT tid, count(*) AS df FROM (%s) x GROUP BY tid) u
               ON u.tid = v.id
    $q$, array_to_string(parts, ' UNION ALL '));
END $$;

-- Delete vocabulary entries appearing in fewer than min_df documents.
--
--   SELECT public.bm25_prune();          -- every bm25vector column, df = 0
--
-- Defaults to min_df = 1, which removes only terms nothing references at all --
-- what deleting documents leaves behind. Raising it deletes terms that are
-- still in use somewhere, and those are the most discriminating terms in the
-- corpus, so it trades recall for a vocabulary row. For retrieval, don't.
--
-- Scoping to a subset of tables is possible and is the dangerous form: a term
-- deleted while an unlisted table still uses it stays in that table's vectors
-- and keeps its index space, but to_bm25_query can no longer map it, so the
-- term silently stops being searchable there. The no-argument form asks the
-- catalogue instead of the caller, which is why it is the default.
--
-- Pruning does not shrink the index. The BM25 index only ever allocated for
-- ids present in a stored vector, so a term nothing references was already
-- absent from it. What it buys is a smaller vocabulary to join against on
-- every search.
CREATE OR REPLACE FUNCTION public.bm25_prune(
    tables regclass[] DEFAULT NULL,
    min_df bigint DEFAULT 1,
    col name DEFAULT NULL
)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE removed bigint;
BEGIN
    DELETE FROM public.bm25_vocabulary v
    USING public.bm25_vocabulary_usage(tables, col) u
    WHERE u.id = v.id AND u.df < min_df;
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END $$;

-- ---------------------------------------------------------------------------
-- Highlighting
-- ---------------------------------------------------------------------------
-- ts_headline alone cannot highlight the scripts this analyzer exists for. It
-- re-parses the document with the configuration's parser, which does not
-- segment Chinese, Japanese, Korean, Thai, Khmer, Lao or Burmese -- so a search
-- that ranked those documents correctly returns them with nothing marked, which
-- reads as a broken search box.
--
-- So: ts_headline for the spaced part, and the analyzer's own terms located in
-- the text for the rest. The second pass runs over the first one's output.
CREATE OR REPLACE FUNCTION public.bm25_headline(
    content   text,
    query     text,
    start_sel text DEFAULT '<b>',
    stop_sel  text DEFAULT '</b>',
    cfg       regconfig DEFAULT 'public.bm25_english'
)
RETURNS text LANGUAGE sql STABLE PARALLEL SAFE AS $$
    WITH marks AS (
        -- Only terms from unspaced scripts, and only those actually present:
        -- an absent term in the alternation would match nothing but still cost
        -- a branch, and a Latin stem would match inside unrelated words.
        SELECT string_agg(t.term, '|' ORDER BY length(t.term) DESC, t.term) AS pattern
        FROM (SELECT DISTINCT term FROM public.bm25_terms(query, cfg)) t
        WHERE t.term ~ public.bm25_script_class()
          AND strpos(content, t.term) > 0
    ),
    spaced AS (
        SELECT ts_headline(cfg, content, websearch_to_tsquery(cfg, query),
            'StartSel="' || replace(start_sel, '"', '\"')
            || '", StopSel="' || replace(stop_sel, '"', '\"') || '"'
            -- Fragmenting would happily discard the CJK half of a document as
            -- uninteresting, since ts_headline cannot see any match in it.
            || CASE WHEN (SELECT pattern FROM marks) IS NULL
                    THEN '' ELSE ', HighlightAll=true' END) AS marked
    )
    SELECT CASE
        WHEN m.pattern IS NULL THEN s.marked
        -- Bigrams are marked one pair at a time, so a four-character match comes
        -- back as two adjacent spans; splicing out the seam between them makes
        -- it one.
        ELSE replace(
                regexp_replace(s.marked, '(' || m.pattern || ')',
                               start_sel || '\1' || stop_sel, 'g'),
                stop_sel || start_sel, '')
    END
    FROM marks m, spaced s;
$$;

-- ---------------------------------------------------------------------------
-- Chunking
-- ---------------------------------------------------------------------------
-- Split a long document into retrievable pieces.
--
--   INSERT INTO chunks (doc_id, seq, content)
--   SELECT d.id, c.seq, c.chunk
--   FROM documents d, LATERAL public.bm25_chunk(d.body) c;
--
-- BM25 scores a whole row, so a 40-page document is one score: the page that
-- answers the query is averaged against thirty-nine that do not, and length
-- normalisation pushes it further down. Chunking is what makes retrieval
-- return a passage rather than a book.
--
-- Splits on sentence boundaries where it can and word boundaries otherwise,
-- never mid-word. `overlap` repeats the tail of each chunk at the head of the
-- next so a sentence spanning a boundary is still wholly present in one of
-- them.
--
-- Sizes are in CHARACTERS, not tokens, and the two diverge sharply by script:
-- measured on real prose, 215 characters of Chinese produce 145 terms where
-- 141 characters of English produce 19. A size tuned on English will produce
-- much denser chunks in CJK -- worth halving it for those corpora.
-- regexp_instr and regexp_count arrived in PostgreSQL 15, and vchord_bm25
-- packages back to 14. Creating this unconditionally would abort the whole
-- script there -- initdb.sh runs with ON_ERROR_STOP -- so the rest of the
-- analyzer would never be installed for the sake of a helper.
DO $do$
BEGIN
IF current_setting('server_version_num')::int < 150000 THEN
    RAISE NOTICE 'bm25: bm25_chunk needs PostgreSQL 15 or newer, skipping';
    RETURN;
END IF;
EXECUTE $fn$
CREATE OR REPLACE FUNCTION public.bm25_chunk(
    content text,
    size    integer DEFAULT 1000,
    overlap integer DEFAULT 100
)
RETURNS TABLE(seq integer, chunk text) LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE ROWS 8 AS $body$
DECLARE
    pos     integer := 1;
    n       integer := length(content);
    cut     integer;
    piece   text;

    stride  integer := GREATEST(size - overlap, 1);
BEGIN
    IF content IS NULL OR n = 0 THEN
        RETURN;
    END IF;
    IF overlap >= size THEN
        RAISE EXCEPTION 'bm25_chunk: overlap (%) must be smaller than size (%)',
                        overlap, size;
    END IF;

    seq := 0;
    WHILE pos <= n LOOP
        piece := substr(content, pos, size);
        EXIT WHEN piece = '';

        -- Not the last chunk, so back up to a boundary. Sentence end first,
        -- then any whitespace. regexp_instr with the occurrence count gives
        -- the LAST match directly; computing it from reverse() and strpos()
        -- is off-by-one bait and an earlier version of this cut mid-word.
        IF pos + size <= n THEN
            cut := 0;
            IF regexp_count(piece, '[.!?。！？]') > 0 THEN
                cut := regexp_instr(piece, '[.!?。！？]', 1,
                                    regexp_count(piece, '[.!?。！？]'), 1) - 1;
            END IF;
            -- Only useful if it leaves a chunk worth keeping; otherwise the
            -- boundary is so early that the chunks would be tiny.
            IF cut <= length(piece) / 3 AND regexp_count(piece, '\s') > 0 THEN
                cut := regexp_instr(piece, '\s', 1,
                                    regexp_count(piece, '\s'), 1) - 1;
            END IF;
            -- Still nothing usable: unspaced CJK with no punctuation. Take the
            -- hard cut, because a chunk that grows until it finds a boundary
            -- is unbounded.
            IF cut > length(piece) / 3 AND cut < length(piece) THEN
                piece := substr(piece, 1, cut);
            END IF;
        END IF;

        cut := length(piece);          -- advance by what was actually emitted
        piece := btrim(piece);
        IF piece <> '' THEN
            seq := seq + 1;
            chunk := piece;
            RETURN NEXT;
        END IF;

        pos := pos + GREATEST(cut - overlap, stride);
    END LOOP;
END $body$;
$fn$;
END $do$;

-- ---------------------------------------------------------------------------
-- Index management
-- ---------------------------------------------------------------------------
-- Attaching BM25 to a table by hand is six statements -- a column, a trigger
-- function, a trigger, an index, and for phrase search a generated tsvector
-- and a GIN index -- and then every query has to name the BM25 index as a
-- string literal, because that is the signature vchord's to_bm25query takes.
-- Rename the index and the literal still parses and silently stops matching.
--
--   SELECT public.bm25_create_index('messages', 'content');
--   SELECT * FROM public.bm25_search('messages', 'sourdough starter', 10);
--   SELECT public.bm25_drop_index('messages');
--
-- The index name is derived from the table, in one place, and the search
-- function resolves it -- so nothing downstream has to know it.

-- Attach BM25 to a table. Idempotent.
--
-- phrase => also add a generated tsvector column and a GIN index, which is what
-- phrase, proximity and boolean search need: a bm25vector is a bag of
-- {term_id:frequency} with no positions, so it cannot answer "these two words,
-- in this order". Off by default -- it costs a second index on every write.
CREATE OR REPLACE FUNCTION public.bm25_create_index(
    tbl     regclass,
    col     name,
    phrase  boolean DEFAULT false,
    cfg     regconfig DEFAULT 'public.bm25_english'
)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    rel  name := (SELECT relname FROM pg_class WHERE oid = tbl);
    nsp  name := (SELECT n.nspname FROM pg_class c JOIN pg_namespace n
                  ON n.oid = c.relnamespace WHERE c.oid = tbl);
    vec  name := col || '_bm25';
    idx  name := rel || '_' || col || '_bm25_idx';
    fn   name := rel || '_' || col || '_bm25_trg';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_attribute
                   WHERE attrelid = tbl AND attname = col AND NOT attisdropped) THEN
        RAISE EXCEPTION 'bm25_create_index: %.% does not exist', tbl, col;
    END IF;

    EXECUTE format('ALTER TABLE %s ADD COLUMN IF NOT EXISTS %I bm25_catalog.bm25vector',
                   tbl, vec);

    -- The configuration is baked into the trigger body rather than read at
    -- write time: a document tokenized under one configuration and queried
    -- under another matches nothing, and that failure is silent.
    EXECUTE format($f$
        CREATE OR REPLACE FUNCTION %I.%I() RETURNS trigger LANGUAGE plpgsql AS $body$
        BEGIN NEW.%I := public.to_bm25(NEW.%I, %L::regconfig); RETURN NEW; END $body$;
    $f$, nsp, fn, vec, col, cfg);

    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', fn, tbl);
    EXECUTE format($f$
        CREATE TRIGGER %I BEFORE INSERT OR UPDATE OF %I ON %s
          FOR EACH ROW EXECUTE FUNCTION %I.%I()
    $f$, fn, col, tbl, nsp, fn);

    -- Backfill BEFORE building the index, not after.
    --
    -- Rows that predate the trigger have a NULL vector, which sorts last and
    -- never matches, so they have to be rewritten either way. Doing it while
    -- the BM25 index already exists makes every one of those rewrites an index
    -- insert as well. Measured on 100,000 rows:
    --
    --     index first, then backfill   2.4s + 28.8s = 31.2s
    --     backfill, then index        19.0s +  2.3s = 21.2s
    --
    -- An earlier version did it the other way round, and on 500,000 rows that
    -- had not finished after 26 minutes.
    EXECUTE format('UPDATE %s SET %I = %I WHERE %I IS NULL', tbl, col, col, vec);

    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON %s USING bm25 (%I bm25_catalog.bm25_ops)',
        idx, tbl, vec);

    IF phrase THEN
        EXECUTE format($f$
            ALTER TABLE %s ADD COLUMN IF NOT EXISTS %I tsvector
              GENERATED ALWAYS AS (to_tsvector(%L::regconfig, %I)) STORED
        $f$, tbl, col || '_ts', cfg, col);
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %s USING gin (%I)',
                       rel || '_' || col || '_ts_idx', tbl, col || '_ts');
    END IF;

    EXECUTE format('ANALYZE %s', tbl);
    ANALYZE public.bm25_vocabulary;
    RETURN idx;
END $$;

-- Remove everything bm25_create_index added. Vocabulary is left alone: it is
-- shared with every other table, so see bm25_prune.
CREATE OR REPLACE FUNCTION public.bm25_drop_index(tbl regclass, col name DEFAULT 'content')
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    rel name := (SELECT relname FROM pg_class WHERE oid = tbl);
    nsp name := (SELECT n.nspname FROM pg_class c JOIN pg_namespace n
                 ON n.oid = c.relnamespace WHERE c.oid = tbl);
BEGIN
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', rel || '_' || col || '_bm25_trg', tbl);
    EXECUTE format('DROP FUNCTION IF EXISTS %I.%I()', nsp, rel || '_' || col || '_bm25_trg');
    EXECUTE format('DROP INDEX IF EXISTS %I.%I', nsp, rel || '_' || col || '_bm25_idx');
    EXECUTE format('DROP INDEX IF EXISTS %I.%I', nsp, rel || '_' || col || '_ts_idx');
    EXECUTE format('ALTER TABLE %s DROP COLUMN IF EXISTS %I', tbl, col || '_bm25');
    EXECUTE format('ALTER TABLE %s DROP COLUMN IF EXISTS %I', tbl, col || '_ts');
END $$;

-- Search several columns at once, with per-column weights.
--
--   SELECT * FROM public.bm25_search_multi(
--       'articles', 'sourdough starter',
--       ARRAY[('title', 3.0), ('body', 1.0)]::public.bm25_field[]);
--
-- This is the equivalent of Elasticsearch's multi_match with `title^3`, and it
-- has to be built rather than configured: a bm25vector is one column, so one
-- column is one field. Call bm25_create_index once per column first.
--
-- Scores are fused by RANK, not by weighted sum of the raw scores. BM25 scores
-- are unbounded negatives whose scale depends on the column's own corpus
-- statistics -- a title field averaging six words and a body averaging six
-- hundred produce numbers that are not comparable, so adding them with weights
-- mostly measures which column has the longer documents. Reciprocal rank
-- fusion compares positions instead, which is scale-free.
--
-- The weight multiplies a column's reciprocal-rank contribution, so 3.0 on
-- title means a title hit is worth three body hits at the same rank.
-- Guarded: analyzer.sql is applied on every start and CREATE TYPE has no
-- IF NOT EXISTS.
DO $do$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'bm25_field' AND n.nspname = 'public'
    ) THEN
        CREATE TYPE public.bm25_field AS (col name, weight real);
    END IF;
END $do$;

CREATE OR REPLACE FUNCTION public.bm25_search_multi(
    tbl    regclass,
    query  text,
    fields public.bm25_field[],
    n      integer DEFAULT 10,
    filter text DEFAULT NULL,
    k      integer DEFAULT 60,
    cfg    regconfig DEFAULT 'public.bm25_english'
)
RETURNS TABLE(id bigint, score real) LANGUAGE plpgsql STABLE ROWS 10 AS $$
DECLARE
    f     public.bm25_field;
    parts text[] := '{}';
BEGIN
    IF fields IS NULL OR cardinality(fields) = 0 THEN
        RAISE EXCEPTION 'bm25_search_multi: name at least one field';
    END IF;

    -- Each column contributes weight / (k + rank). k is the standard RRF
    -- constant: raising it flattens the advantage of the top few positions.
    FOREACH f IN ARRAY fields LOOP
        IF f.weight IS NULL OR f.weight <= 0 THEN
            RAISE EXCEPTION 'bm25_search_multi: weight for % must be positive', f.col;
        END IF;
        -- ::numeric on the weight is load-bearing. format('%s') renders a real
        -- 3.0 as the text "3", and "3 / (60 + rank)" is integer division --
        -- which is 0 for every row, silently, so every document ties at zero
        -- and the weights do nothing at all.
        parts := parts || format(
            'SELECT s.id, (%s::numeric / (%s + row_number() OVER (ORDER BY s.score)))::real AS c '
            'FROM public.bm25_search(%L::regclass, %L, %s, %L, %L, 0, %L::regconfig) s',
            f.weight, k, tbl::text, query, n * 10, f.col, filter, cfg);
    END LOOP;

    RETURN QUERY EXECUTE format($q$
        SELECT x.id, sum(x.c)::real AS score
        FROM (%s) x
        GROUP BY x.id
        ORDER BY 2 DESC
        LIMIT %s
    $q$, array_to_string(parts, ' UNION ALL '), n);
END $$;

-- Rebuild a table's vectors under a new analyzer, without a full-table
-- rewrite in one transaction and without the index going away underneath
-- readers.
--
--   CALL public.bm25_reindex('messages', 'content');
--
-- The documented alternative is `UPDATE messages SET content = content`
-- followed by REINDEX. That is one transaction over the whole table -- it
-- holds row locks on everything it touches until it commits, doubles the
-- table on disk before any VACUUM can run, and leaves the index stale until
-- the REINDEX finishes. On a live retrieval backend it is close to an outage.
--
-- This writes into a shadow column in committed batches, so readers keep using
-- the existing column and index the whole time, and a failure part-way leaves
-- a half-filled shadow column rather than a half-rewritten table. The swap at
-- the end is a rename, which is atomic and brief.
--
-- A PROCEDURE rather than a FUNCTION because only a procedure can COMMIT, and
-- committing between batches is the entire point.
--
-- Writes during the rebuild are handled by making the trigger populate both
-- columns, so the shadow cannot go stale under concurrent ingest.
--
-- The one window that does block writes is the CREATE INDEX on the shadow
-- column, which takes a SHARE lock: reads continue, writes wait. CONCURRENTLY
-- is not available here because it cannot run inside a transaction block, and
-- a procedure body is always in one even after COMMIT.
CREATE OR REPLACE PROCEDURE public.bm25_reindex(
    tbl   regclass,
    col   name DEFAULT 'content',
    cfg   regconfig DEFAULT 'public.bm25_english',
    batch integer DEFAULT 5000
)
LANGUAGE plpgsql AS $$
DECLARE
    rel     name := (SELECT relname FROM pg_class WHERE oid = tbl);
    nsp     name := (SELECT n.nspname FROM pg_class c JOIN pg_namespace n
                     ON n.oid = c.relnamespace WHERE c.oid = tbl);
    vec     name := col || '_bm25';
    shadow  name := col || '_bm25_rebuild';
    idx     name := rel || '_' || col || '_bm25_idx';
    newidx  name := rel || '_' || col || '_bm25_rebuild_idx';
    fn      name := rel || '_' || col || '_bm25_trg';
    moved   bigint;
    total   bigint := 0;
BEGIN
    EXECUTE format('ALTER TABLE %s DROP COLUMN IF EXISTS %I', tbl, shadow);
    EXECUTE format('ALTER TABLE %s ADD COLUMN %I bm25_catalog.bm25vector', tbl, shadow);

    -- Dual-write, so concurrent ingest lands in both columns.
    EXECUTE format($f$
        CREATE OR REPLACE FUNCTION %I.%I() RETURNS trigger LANGUAGE plpgsql AS $body$
        BEGIN
            NEW.%I := public.to_bm25(NEW.%I);
            NEW.%I := public.to_bm25(NEW.%I, %L::regconfig);
            RETURN NEW;
        END $body$;
    $f$, nsp, fn, vec, col, shadow, col, cfg);
    COMMIT;

    LOOP
        EXECUTE format($f$
            UPDATE %s SET %I = public.to_bm25(%I, %L::regconfig)
            WHERE ctid IN (SELECT ctid FROM %s WHERE %I IS NULL LIMIT %s)
        $f$, tbl, shadow, col, cfg, tbl, shadow, batch);
        GET DIAGNOSTICS moved = ROW_COUNT;
        total := total + moved;
        COMMIT;
        EXIT WHEN moved = 0;
        RAISE NOTICE 'bm25_reindex: % rows rebuilt', total;
    END LOOP;

    EXECUTE format(
        'CREATE INDEX %I ON %s USING bm25 (%I bm25_catalog.bm25_ops)',
        newidx, tbl, shadow);
    COMMIT;

    -- Cutover. Renames only, so it is brief even on a large table.
    EXECUTE format('DROP INDEX %I.%I', nsp, idx);
    EXECUTE format('ALTER TABLE %s DROP COLUMN %I', tbl, vec);
    EXECUTE format('ALTER TABLE %s RENAME COLUMN %I TO %I', tbl, shadow, vec);
    EXECUTE format('ALTER INDEX %I.%I RENAME TO %I', nsp, newidx, idx);
    EXECUTE format($f$
        CREATE OR REPLACE FUNCTION %I.%I() RETURNS trigger LANGUAGE plpgsql AS $body$
        BEGIN NEW.%I := public.to_bm25(NEW.%I, %L::regconfig); RETURN NEW; END $body$;
    $f$, nsp, fn, vec, col, cfg);
    COMMIT;

    EXECUTE format('ANALYZE %s', tbl);
    RAISE NOTICE 'bm25_reindex: % rows, cutover complete', total;
END $$;

-- Search. Returns (id, score, ctid) -- join back to the table for the columns
-- you want, or use bm25_search_sql below to build a query over your own SELECT.
--
-- The index name never appears in caller code.
--
-- `filter` is raw SQL appended to the WHERE clause. That makes it a trusted
-- input: it is the schema author's expression, never a user's. To put a user's
-- *value* in it, write a placeholder and pass the value in `params` --
-- $1, $2 … are substituted as properly quoted literals, so quotes, backslashes
-- and NULLs cannot terminate the expression:
--
--   public.bm25_search('messages', 'bread', 10, 'content',
--                      'locale = $1 AND author = $2',
--                      params => ARRAY[user_locale, user_name])
--
-- Interpolating the same values into the string yourself is what this exists
-- to avoid.
CREATE OR REPLACE FUNCTION public.bm25_search(
    tbl    regclass,
    query  text,
    n      integer DEFAULT 10,
    col    name DEFAULT 'content',
    filter text DEFAULT NULL,
    skip   integer DEFAULT 0,
    cfg    regconfig DEFAULT 'public.bm25_english',
    fuzzy  boolean DEFAULT false,
    threshold real DEFAULT 0.4,
    params text[] DEFAULT NULL
)
RETURNS TABLE(id bigint, score real, row_ctid tid) LANGUAGE plpgsql STABLE ROWS 10 AS $$
DECLARE
    rel name := (SELECT relname FROM pg_class WHERE oid = tbl);
    idx text := quote_literal(rel || '_' || col || '_bm25_idx');
    -- fuzzy rewrites each query term to the nearest one in the vocabulary, so
    -- a misspelling matches instead of returning nothing. Off by default: it
    -- is a trigram lookup per unknown term, and silently correcting a term the
    -- user meant literally is worse than returning nothing.
    -- The query vector is built ONCE, here, and inlined into the generated SQL
    -- as a literal.
    --
    -- Not as a function call: the score expression appears twice, in the
    -- projection and in the match predicate, and the planner puts the second
    -- one in a Filter that re-evaluates it for every candidate row the index
    -- returns. With to_bm25_query at a fraction of a millisecond that is
    -- invisible. With to_bm25_query_fuzzy, which does a trigram lookup per
    -- unknown term and cost 197 ms on a 60,000-term vocabulary, the same query
    -- took 106 SECONDS at 500,000 documents. Computing it once turns that back
    -- into one evaluation per query.
    qvec  bm25_catalog.bm25vector;
    qexpr text;
    pk    name;
    i     int;
BEGIN
    IF fuzzy THEN
        IF to_regprocedure('public.to_bm25_query_fuzzy(text,real,regconfig)') IS NULL THEN
            RAISE EXCEPTION 'bm25_search: fuzzy needs pg_trgm, which is not installed';
        END IF;
        qvec := public.to_bm25_query_fuzzy(query, threshold, cfg);
    ELSE
        qvec := public.to_bm25_query(query, cfg);
    END IF;
    qexpr := format('%L::bm25_catalog.bm25vector', qvec::text);

    -- Substitute $n placeholders in the filter with quoted literals. Highest
    -- index first, so $10 is not eaten by the pattern for $1.
    IF params IS NOT NULL AND filter IS NOT NULL THEN
        FOR i IN REVERSE cardinality(params)..1 LOOP
            filter := replace(filter, '$' || i,
                              CASE WHEN params[i] IS NULL THEN 'NULL'
                                   ELSE quote_literal(params[i]) END);
        END LOOP;
    END IF;
    IF params IS NULL AND filter ~ '\$[0-9]' THEN
        RAISE EXCEPTION 'bm25_search: filter has placeholders but no params were given';
    END IF;

    SELECT a.attname INTO pk
    FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid
                                       AND a.attnum = i.indkey[0]
    WHERE i.indrelid = tbl AND i.indisprimary;

    -- `score < 0` is the match test, and it is not optional. A bm25vector
    -- sharing no term with the query scores exactly 0, and whether those rows
    -- reach the caller depends on the plan -- an index scan drops them, a
    -- sequential scan on a small table does not. Without this the same call
    -- returns hits on a large table and every row on a small one. Filtering
    -- makes it a search rather than a sort.
    RETURN QUERY EXECUTE format($q$
        SELECT %s::bigint,
               (%I <&> bm25_catalog.to_bm25query(%s, %s))::real,
               ctid
        FROM %s
        WHERE (%s)
          AND (%I <&> bm25_catalog.to_bm25query(%s, %s)) < 0
        ORDER BY 2
        LIMIT %s OFFSET %s
    $q$, COALESCE(quote_ident(pk), 'NULL'), col || '_bm25', idx, qexpr,
         tbl, COALESCE(filter, 'true'),
         col || '_bm25', idx, qexpr, n, skip);
END $$;

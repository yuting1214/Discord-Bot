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

CREATE OR REPLACE FUNCTION public.bm25_runs(content text)
RETURNS TABLE(script text, run text) LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT public.bm25_script_of(m.run), m.run
    FROM (SELECT (regexp_matches(content, public.bm25_script_class() || '+', 'g'))[1]) AS m(run);
$$;

-- ---------------------------------------------------------------------------
-- Segmenters
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.bm25_bigrams(run text)
RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
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
            RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $body$
                -- tag 0 is punctuation and whitespace; everything else is a word.
                SELECT lower(w.contents)
                FROM public.icu_word_boundaries(run, locale) w
                WHERE w.tag <> 0;
            $body$;
        $f$;
    ELSE
        EXECUTE $f$
            CREATE OR REPLACE FUNCTION public.bm25_words(run text, locale text)
            RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $body$
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
RETURNS SETOF text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
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
RETURNS TABLE(term text) LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
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

-- Write path: VOLATILE, because it extends the vocabulary with unseen terms.
CREATE OR REPLACE FUNCTION public.to_bm25(
    content text,
    cfg regconfig DEFAULT 'public.bm25_english'
)
RETURNS bm25_catalog.bm25vector LANGUAGE plpgsql AS $$
DECLARE result bm25_catalog.bm25vector;
BEGIN
    INSERT INTO public.bm25_vocabulary (term)
    SELECT DISTINCT term FROM public.bm25_terms(content, cfg)
    ON CONFLICT (term) DO NOTHING;

    -- Term ids must ascend; the type rejects unsorted input.
    SELECT COALESCE('{' || string_agg(v.id || ':' || t.freq, ', ' ORDER BY v.id) || '}', '{}')
             ::bm25_catalog.bm25vector
    INTO result
    FROM (SELECT term, count(*) AS freq
          FROM public.bm25_terms(content, cfg) GROUP BY term) t
    JOIN public.bm25_vocabulary v ON v.term = t.term;
    RETURN result;
END $$;

-- A single-character query in a segmented script is a real word -- 빵 (bread),
-- 麵 (noodle) -- but it is almost never a term, because the document that
-- contains it was segmented into 빵에 or 麵包. Without this, those queries
-- return nothing at all. Expanded to the short vocabulary terms containing that
-- character, capped so an unlucky common character cannot turn one query term
-- into hundreds.
CREATE OR REPLACE FUNCTION public.bm25_expand_term(t text, cap int DEFAULT 16)
RETURNS SETOF text LANGUAGE sql STABLE PARALLEL SAFE AS $$
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
                    (SELECT v.term FROM public.bm25_vocabulary v
                     WHERE v.term % t AND public.similarity(v.term, t) >= threshold
                     ORDER BY public.similarity(v.term, t) DESC LIMIT 1),
                    t);
            $body$;
        $f$;
    END IF;
END $do$;

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

-- Attach to a table:
--
--   ALTER TABLE messages ADD COLUMN bm25 bm25_catalog.bm25vector;
--
--   CREATE FUNCTION messages_bm25_trg() RETURNS trigger LANGUAGE plpgsql AS $fn$
--   BEGIN NEW.bm25 := public.to_bm25(NEW.content); RETURN NEW; END $fn$;
--
--   CREATE TRIGGER messages_bm25 BEFORE INSERT OR UPDATE OF content ON messages
--     FOR EACH ROW EXECUTE FUNCTION messages_bm25_trg();
--
--   CREATE INDEX messages_bm25_idx ON messages USING bm25 (bm25 bm25_catalog.bm25_ops);
--
-- Query (<&> returns negative scores; more negative is more relevant):
--
--   SELECT id FROM messages
--   ORDER BY bm25 <&> bm25_catalog.to_bm25query('messages_bm25_idx',
--                                               public.to_bm25_query('search terms'))
--   LIMIT 5;

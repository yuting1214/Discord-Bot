-- BM25 text analysis without pg_tokenizer.
--
-- A bm25vector is a sparse {term_id:frequency} map. Nothing requires those ids
-- to come from pg_tokenizer, which costs ~331MB of resident memory because it
-- preloads tokenizer models. This produces the same vectors from Postgres' own
-- text search plus bigrams for unspaced scripts, at ~0.3MB.
--
-- Spaced scripts   : to_tsvector supplies stemming and stopwords.
-- Unspaced scripts : CJK, Thai, Lao, Khmer and Myanmar are indexed as
--                    overlapping character bigrams, the strategy Lucene's
--                    CJKAnalyzer uses. Character unigrams -- what pg_tokenizer's
--                    unicode_segmentation produces -- rank decoys above the
--                    correct document, because individual characters are far
--                    too common to discriminate.
--
-- Idempotent: safe to run on every start.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;

-- ---------------------------------------------------------------------------
-- Text search configuration
-- ---------------------------------------------------------------------------
-- vchord_bm25 allocates roughly 8KB of index per distinct term id, near enough
-- independently of how many documents contain it. Vocabulary cardinality, not
-- corpus size, is therefore what drives index size: 20,000 documents carrying
-- one unique token each measured a 157MB index, against 1.3MB for the same
-- 20,000 documents of ordinary prose.
--
-- Chat and log data is full of exactly those tokens -- snowflake ids, hashes,
-- URLs, version strings -- and each one would buy a permanent 8KB posting list
-- to match a single document. Postgres' parser already labels them, so they are
-- dropped by unmapping their token types rather than by pattern-matching the
-- output. Numbers stay searchable as part of a phrase's other words; they are
-- simply not terms of their own.
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

-- ---------------------------------------------------------------------------
-- Vocabulary
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bm25_vocabulary (
    id   serial PRIMARY KEY,
    term text UNIQUE NOT NULL
);

-- Character classes for the scripts to_tsvector cannot segment, written once
-- because getting them out of step between the write path and the read path
-- would silently stop those documents matching.
--
--   3400-4DBF  CJK extension A          4E00-9FFF  CJK unified
--   F900-FAFF  CJK compatibility        3041-30FF  hiragana + katakana
--   31F0-31FF  katakana phonetic ext    FF66-FF9F  halfwidth katakana
--                                                  (through FF9F: the voiced
--                                                  sound marks are separate
--                                                  characters and would
--                                                  otherwise split a run)
--   AC00-D7A3  hangul syllables         3130-318F  hangul compatibility jamo
--   0E01-0E5B  Thai                     0E81-0EDF  Lao
--   1780-17FF  Khmer                    1000-109F  Myanmar
--   20000-2A6DF  CJK extension B
CREATE OR REPLACE FUNCTION public.bm25_script_class()
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT '[㐀-䶿一-鿿豈-﫿ぁ-ヿㇰ-ㇿｦ-ﾟ가-힣㄰-㆏ก-๛ກ-ໟក-៿က-႟\U00020000-\U0002A6DF]';
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
    -- one huge token.
    SELECT lexeme
    FROM unnest(to_tsvector(
        cfg, regexp_replace(content, public.bm25_script_class() || '+', ' ', 'g')))
    -- A term longer than this is a base64 blob or a stack frame, never a word,
    -- and would cost the same 8KB of index as a real one.
    WHERE length(lexeme) <= 64
    UNION ALL
    -- Unspaced scripts: overlapping bigrams; a lone character indexes as itself
    -- so that single-character queries still match.
    SELECT CASE WHEN length(run) = 1 THEN run ELSE substr(run, i, 2) END
    FROM (SELECT (regexp_matches(content, public.bm25_script_class() || '+', 'g'))[1] AS run) r,
         LATERAL generate_series(1, GREATEST(length(r.run) - 1, 1)) AS i;
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
    FROM (SELECT term, count(*) AS freq
          FROM public.bm25_terms(content, cfg) GROUP BY term) t
    JOIN public.bm25_vocabulary v ON v.term = t.term;
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

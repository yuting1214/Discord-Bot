-- BM25 text analysis without pg_tokenizer.
--
-- A bm25vector is a sparse {term_id:frequency} map. Nothing requires those ids
-- to come from pg_tokenizer, which costs ~331MB of resident memory because it
-- preloads tokenizer models. This produces the same vectors from Postgres' own
-- text search plus CJK bigrams, at ~0.3MB.
--
-- Latin text  : to_tsvector supplies stemming and stopwords.
-- CJK text    : indexed as overlapping character bigrams, the strategy Lucene's
--               CJKAnalyzer uses. Character unigrams -- what pg_tokenizer's
--               unicode_segmentation produces -- rank decoys above the correct
--               document, because individual CJK characters are far too common.
--
-- Idempotent: safe to run on every start.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;

CREATE TABLE IF NOT EXISTS bm25_vocabulary (
    id   serial PRIMARY KEY,
    term text UNIQUE NOT NULL
);

-- Every identifier is schema-qualified. A SQL function resolves types against
-- the caller's search_path when it is inlined, so an unqualified bm25vector
-- fails for any caller that has not put bm25_catalog on its path.
CREATE OR REPLACE FUNCTION public.bm25_terms(content text, cfg regconfig DEFAULT 'english')
RETURNS TABLE(term text) LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    -- Latin: CJK runs are blanked out first so they do not become one huge token.
    SELECT lexeme
    FROM unnest(to_tsvector(cfg, regexp_replace(content, '[一-鿿ぁ-ヿ가-힣]+', ' ', 'g')))
    UNION ALL
    -- CJK: overlapping bigrams; a lone character indexes as itself so that
    -- single-character queries still match.
    SELECT CASE WHEN length(run) = 1 THEN run ELSE substr(run, i, 2) END
    FROM (SELECT (regexp_matches(content, '[一-鿿ぁ-ヿ가-힣]+', 'g'))[1] AS run) r,
         LATERAL generate_series(1, GREATEST(length(r.run) - 1, 1)) AS i;
$$;

-- Write path: VOLATILE, because it extends the vocabulary with unseen terms.
CREATE OR REPLACE FUNCTION public.to_bm25(content text, cfg regconfig DEFAULT 'english')
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
CREATE OR REPLACE FUNCTION public.to_bm25_query(content text, cfg regconfig DEFAULT 'english')
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

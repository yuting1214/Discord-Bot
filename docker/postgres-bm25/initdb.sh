#!/bin/bash
# Runs once, on the first boot of an empty volume, from
# /docker-entrypoint-initdb.d.
#
# A stock postgres-ssl has only plpgsql enabled even though pgvector is sitting
# on disk, so every deployer's first act is to work out which CREATE EXTENSION
# statements to run. This does it for them.
#
#   BM25_EXTENSIONS   comma-separated, or "none" to skip entirely
#   BM25_ANALYZER     off to skip the multilingual analyzer
#
# Existing volumes are not touched -- Docker only runs this directory on
# initialisation. To apply it to a database that already exists, run
# analyzer.sql by hand; it is idempotent.
set -e

EXTENSIONS="${BM25_EXTENSIONS:-vector,vchord_bm25,icu_ext,unaccent,pg_trgm,btree_gin,fuzzystrmatch}"

if [ "$EXTENSIONS" != "none" ]; then
    IFS=','
    for ext in $EXTENSIONS; do
        ext="$(echo "$ext" | tr -d '[:space:]')"
        [ -z "$ext" ] && continue
        # CASCADE because vchord_bm25 depends on others being present first, and
        # one unavailable extension must not abort the remaining list.
        if psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
                -c "CREATE EXTENSION IF NOT EXISTS \"$ext\" CASCADE" >/dev/null 2>&1; then
            echo "postgres-bm25: extension $ext ready"
        else
            echo "postgres-bm25: extension $ext unavailable, skipped"
        fi
    done
    unset IFS
fi

if [ "${BM25_ANALYZER:-on}" != "off" ] && [ -f /usr/local/share/postgres-bm25/analyzer.sql ]; then
    if psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
            -f /usr/local/share/postgres-bm25/analyzer.sql >/dev/null; then
        echo "postgres-bm25: analyzer installed (to_bm25, to_bm25_query, bm25_terms)"
    else
        echo "postgres-bm25: analyzer failed to install" >&2
    fi
fi

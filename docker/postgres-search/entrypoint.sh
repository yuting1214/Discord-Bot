#!/bin/bash
# Appends the preload list to the postgres command line, then hands over to
# Railway's wrapper unchanged.
#
# The preload list cannot be left to postgresql.conf: a command-line `-c`
# overrides the file, and the base image's CMD already passes some, so anything
# a deployer writes into postgresql.conf for shared_preload_libraries is
# silently ignored. Setting it here is the only place a deployer can influence
# it without rebuilding the image.
#
# Why not simply make CMD a shell command that expands the variable: the
# official docker-entrypoint.sh decides whether to run initdb by testing
# whether "$1" is `postgres`. Wrapping the command in `sh -c` makes "$1" `sh`,
# first-time initialisation never runs, and the database comes up empty.
set -e

PRELOAD="${SHARED_PRELOAD_LIBRARIES:-vchord_bm25}"

# vchord_bm25 defaults bm25_limit to 100, and it caps what the index scan
# yields rather than what the query asked for -- so `LIMIT 2000` returns 100
# rows and `OFFSET 100` returns an empty page, in 3ms, with no error. That is
# the worst kind of default for a database other people deploy: it does not
# fail, it silently truncates.
#
# 2000 covers 200 pages of ten and any realistic reranking window, and bounds
# the worst case per query.
#
# NOT -1, upstream's exhaustive setting, even though it never truncates. The
# exhaustive scan costs a full pass whenever the result set is smaller than the
# window asked for -- which includes every query that matches nothing, and a
# search box produces those constantly through typos and rare terms. Measured
# on 20,000 documents:
#
#                            limit=100  limit=2000  limit=20000  limit=-1
#     high-yield query          3.1ms      2.4ms       2.2ms       3.4ms
#     query matching nothing    2.1ms      1.7ms       1.5ms     281.2ms
#     page past the results     7.8ms      6.4ms       6.9ms     439.4ms
#
# An earlier revision of this file defaulted to -1 on the strength of
# measurements that only ever ran high-yield queries, where it does win. It
# does not win where it matters.
#
# Raising this is close to free when result sets are small -- 20000 measured no
# worse than 2000 above -- and only costs on genuinely large ones. Raise it if
# you page deeper than 200 pages; a page past the cap comes back empty rather
# than short.
BM25_LIMIT="${BM25_LIMIT:-2000}"

# bm25_catalog.enable_prefilter is what makes a filtered search CORRECT, not
# merely fast: it pushes the WHERE clause into the index scan so the candidate
# set is drawn from rows that pass the filter, instead of filtering a top-k
# that was already truncated without knowing about it.
#
# Measured on 50,000 documents, against ground truth taken with the index
# disabled entirely:
#
#                        ground truth   prefilter=on   prefilter=off
#     filter ~0.2%          10 rows        10 rows         8 rows
#     filter ~0.02%          9 rows         9 rows         0 rows
#
# Off, a selective filter silently loses matches. Upstream defaults it on, but
# it is absent from their documented GUC list, so it is pinned here rather than
# left to a default that is not promised anywhere.
BM25_PREFILTER="${BM25_PREFILTER:-on}"

# Anything that is not the server runs directly. wrapper.sh asserts the Railway
# volume mount path and PGDATA before it starts anything, which is right for the
# database and wrong for `docker run <image> psql "$DATABASE_URL"` -- that has no
# volume and no PGDATA, and it is the most convenient client on hand for a
# database built around extensions the stock psql image knows nothing about.
if [ "$1" != "postgres" ]; then
    exec "$@"
fi

exec /usr/local/bin/wrapper.sh "$@" \
    -c "shared_preload_libraries=${PRELOAD}" \
    -c "bm25_catalog.bm25_limit=${BM25_LIMIT}" \
    -c "bm25_catalog.enable_prefilter=${BM25_PREFILTER}"

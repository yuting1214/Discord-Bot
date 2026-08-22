# PostgreSQL for this template: pgvector + BM25, on Railway's own image.
#
# Railway's postgres-ssl is not plain Postgres — it bundles pgvector, pgBackRest
# backups and the SSL wrapper. Adopting a third-party search image (ParadeDB and
# friends) would trade all of that away to gain one extension, so the BM25
# extension is layered on top instead.
#
# VectorChord rather than ParadeDB's pg_search. NOT on packaging: pg_search does
# publish Debian packages, including postgresql-18-pg-search_...-trixie_amd64.deb,
# which matches this base exactly. An earlier revision of this file claimed
# otherwise; that claim was wrong, from a truncated listing of the release assets.
#
# The actual reasons:
#   * Licence. ParadeDB is AGPL-3.0. This image is meant to be deployed by other
#     people, and AGPL on the database engine is a constraint many of them cannot
#     accept. VectorChord is permissively licensed.
#   * Size. pg_search's shared object is ~143 MB against roughly 2 MB.
#
# On memory the two are close, not orders apart -- see README.
#
# MEMORY: measured idle anon memory, identical conditions, native (no emulation):
#
#     stock Railway postgres-ssl ............  6.4 MB
#     + vchord_bm25 .........................  6.5 MB   <- this image
#     + pg_tokenizer ........................ 337.5 MB
#
# pg_tokenizer costs ~331 MB because it preloads tokenizer models, and it is
# deliberately NOT installed. Tokenizing with Postgres' own text search instead
# keeps the container ~50x smaller in memory, which is the difference between a
# competitive database service and an expensive one. See README.md for the
# vocabulary + trigger approach that replaces it, and for the CJK trade-off.

ARG PG_MAJOR=18
ARG PG_TAG=18.6

# ---- Fetch stage: download packages without adding curl to the final image ----
FROM debian:trixie-slim AS fetch

ARG PG_MAJOR
ARG VCHORD_BM25_VERSION=0.3.0
# Declared bare on purpose. BuildKit fills this in from --platform, but only
# when the ARG has no default of its own: with `ARG TARGETARCH=amd64` an arm64
# build silently downloads the amd64 package and fails at dpkg.
ARG TARGETARCH

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    mkdir -p /packages; \
    curl -fsSL -o "/packages/vchord-bm25.deb" \
      "https://github.com/tensorchord/VectorChord-bm25/releases/download/${VCHORD_BM25_VERSION}/postgresql-${PG_MAJOR}-vchord-bm25_${VCHORD_BM25_VERSION}-1_${TARGETARCH}.deb"; \
    # icu_ext comes from pgdg rather than a GitHub release, so the repo has to
    # exist here to download it. apt-get download, not install: nothing is
    # unpacked in this stage, and the package lists never reach the final image.
    curl -fsSL -o /etc/apt/trusted.gpg.d/pgdg.asc \
      "https://www.postgresql.org/media/keys/ACCC4CF8.asc"; \
    echo "deb http://apt.postgresql.org/pub/repos/apt trixie-pgdg main ${PG_MAJOR}" \
      > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    cd /packages && apt-get download "postgresql-${PG_MAJOR}-icu-ext"; \
    mv "/packages/postgresql-${PG_MAJOR}-icu-ext"_*.deb /packages/icu-ext.deb

# ---- Final stage: Railway's Postgres, plus BM25 ----
FROM ghcr.io/railwayapp-templates/postgres-ssl:${PG_TAG}

ARG PG_MAJOR
ARG PG_TAG
ARG VCHORD_BM25_VERSION=0.3.0

LABEL org.opencontainers.image.title="postgres-bm25" \
      org.opencontainers.image.description="Railway postgres-ssl with pgvector, BM25 and multilingual search" \
      org.opencontainers.image.source="https://github.com/yuting1214/Discord-Bot" \
      org.opencontainers.image.licenses="MIT" \
      com.railway.postgres-ssl.tag="${PG_TAG}" \
      ai.vectorchord.bm25.version="${VCHORD_BM25_VERSION}"

COPY --from=fetch /packages/*.deb /tmp/

# dpkg only: apt-get update would pull package lists into the layer for no gain.
RUN set -eux; \
    dpkg -i /tmp/vchord-bm25.deb /tmp/icu-ext.deb; \
    rm -f /tmp/*.deb; \
    test -f "/usr/lib/postgresql/${PG_MAJOR}/lib/vchord_bm25.so"; \
    test -f "/usr/lib/postgresql/${PG_MAJOR}/lib/icu_ext.so"; \
    # tsearch_data ships root:root 755, and CREATE TEXT SEARCH DICTIONARY reads
    # its stopword and synonym files from there by name -- so a deployer cannot
    # install a custom dictionary at all without this. Costs nothing.
    chown postgres:postgres "/usr/share/postgresql/${PG_MAJOR}/tsearch_data"

# The analyzer is the same file the application ships; tests keep the two
# byte-identical. It lives outside initdb.d because it must run after the
# extensions, and initdb.d runs in filename order regardless of dependencies.
COPY analyzer.sql /usr/local/share/postgres-bm25/analyzer.sql
COPY initdb.sh /docker-entrypoint-initdb.d/10-postgres-bm25.sh
COPY entrypoint.sh /usr/local/bin/postgres-bm25-entrypoint.sh

RUN chmod 0755 /usr/local/bin/postgres-bm25-entrypoint.sh \
               /docker-entrypoint-initdb.d/10-postgres-bm25.sh

# vchord_bm25 must be preloaded or CREATE EXTENSION fails outright, and the
# preload list can only be set on the command line -- see entrypoint.sh. CMD
# keeps `postgres` as its first word because the official entrypoint tests for
# it to decide whether to initialise the database.
#
# Do not override the command at deploy time: doing so drops the arguments
# Railway's wrapper needs (`-p 5432 -c listen_addresses=*`) and the server
# never starts.
ENTRYPOINT ["postgres-bm25-entrypoint.sh"]
CMD ["postgres", "-p", "5432", "-c", "listen_addresses=*"]

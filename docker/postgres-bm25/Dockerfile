# PostgreSQL for this template: pgvector + BM25, on Railway's own image.
#
# Railway's postgres-ssl is not plain Postgres — it bundles pgvector, pgBackRest
# backups and the SSL wrapper. Adopting a third-party search image (ParadeDB and
# friends) would trade all of that away to gain one extension, so the BM25
# extensions are layered on top instead.
#
# VectorChord rather than ParadeDB's pg_search purely on packaging: pg_search
# ships Linux RPMs only, and this base is Debian, so it would mean compiling
# Rust/pgrx from source. VectorChord publishes .deb for pg14-18.

ARG PG_MAJOR=18
ARG PG_TAG=18.6

# ---- Fetch stage: download packages without adding curl to the final image ----
FROM debian:trixie-slim AS fetch

ARG PG_MAJOR
ARG VCHORD_BM25_VERSION=0.3.0
ARG PG_TOKENIZER_VERSION=0.1.1
ARG TARGETARCH=amd64

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    mkdir -p /packages; \
    curl -fsSL -o "/packages/vchord-bm25.deb" \
      "https://github.com/tensorchord/VectorChord-bm25/releases/download/${VCHORD_BM25_VERSION}/postgresql-${PG_MAJOR}-vchord-bm25_${VCHORD_BM25_VERSION}-1_${TARGETARCH}.deb"; \
    curl -fsSL -o "/packages/pg-tokenizer.deb" \
      "https://github.com/tensorchord/pg_tokenizer.rs/releases/download/${PG_TOKENIZER_VERSION}/postgresql-${PG_MAJOR}-pg-tokenizer_${PG_TOKENIZER_VERSION}-1_${TARGETARCH}.deb"

# ---- Final stage: Railway's Postgres, plus the two extensions ----
FROM ghcr.io/railwayapp-templates/postgres-ssl:${PG_TAG}

ARG PG_MAJOR
ARG PG_TAG
ARG VCHORD_BM25_VERSION=0.3.0
ARG PG_TOKENIZER_VERSION=0.1.1

LABEL org.opencontainers.image.title="postgres-bm25" \
      org.opencontainers.image.description="Railway postgres-ssl with pgvector, vchord_bm25 and pg_tokenizer" \
      org.opencontainers.image.source="https://github.com/yuting1214/Discord-Bot" \
      org.opencontainers.image.licenses="MIT" \
      com.railway.postgres-ssl.tag="${PG_TAG}" \
      ai.vectorchord.bm25.version="${VCHORD_BM25_VERSION}" \
      ai.vectorchord.tokenizer.version="${PG_TOKENIZER_VERSION}"

COPY --from=fetch /packages/*.deb /tmp/

# dpkg only: apt-get update would pull package lists into the layer for no gain.
RUN set -eux; \
    dpkg -i /tmp/vchord-bm25.deb /tmp/pg-tokenizer.deb; \
    rm -f /tmp/*.deb; \
    test -f "/usr/lib/postgresql/${PG_MAJOR}/lib/vchord_bm25.so"; \
    test -f "/usr/lib/postgresql/${PG_MAJOR}/lib/pg_tokenizer.so"

# Both extensions must be preloaded or CREATE EXTENSION fails outright.
# Baked into CMD rather than left to the deployer: Railway's entrypoint is
# wrapper.sh, and overriding the command at deploy time drops the arguments it
# needs (`-p 5432 -c listen_addresses=*`) and the server never starts.
CMD ["postgres", "-p", "5432", "-c", "listen_addresses=*", \
     "-c", "shared_preload_libraries=pg_tokenizer,vchord_bm25"]

# PostgreSQL for this template: pgvector + BM25, on Railway's own image.
#
# Railway's postgres-ssl is not plain Postgres — it bundles pgvector, pgBackRest
# backups and the SSL wrapper. Adopting a third-party search image (ParadeDB and
# friends) would trade all of that away to gain one extension, so the BM25
# extension is layered on top instead.
#
# VectorChord rather than ParadeDB's pg_search purely on packaging: pg_search
# ships Linux RPMs only, and this base is Debian, so it would mean compiling
# Rust/pgrx from source. VectorChord publishes .deb for pg14-18.
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
ARG TARGETARCH=amd64

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    mkdir -p /packages; \
    curl -fsSL -o "/packages/vchord-bm25.deb" \
      "https://github.com/tensorchord/VectorChord-bm25/releases/download/${VCHORD_BM25_VERSION}/postgresql-${PG_MAJOR}-vchord-bm25_${VCHORD_BM25_VERSION}-1_${TARGETARCH}.deb"

# ---- Final stage: Railway's Postgres, plus BM25 ----
FROM ghcr.io/railwayapp-templates/postgres-ssl:${PG_TAG}

ARG PG_MAJOR
ARG PG_TAG
ARG VCHORD_BM25_VERSION=0.3.0

LABEL org.opencontainers.image.title="postgres-bm25" \
      org.opencontainers.image.description="Railway postgres-ssl with pgvector and vchord_bm25" \
      org.opencontainers.image.source="https://github.com/yuting1214/Discord-Bot" \
      org.opencontainers.image.licenses="MIT" \
      com.railway.postgres-ssl.tag="${PG_TAG}" \
      ai.vectorchord.bm25.version="${VCHORD_BM25_VERSION}"

COPY --from=fetch /packages/*.deb /tmp/

# dpkg only: apt-get update would pull package lists into the layer for no gain.
RUN set -eux; \
    dpkg -i /tmp/vchord-bm25.deb; \
    rm -f /tmp/*.deb; \
    test -f "/usr/lib/postgresql/${PG_MAJOR}/lib/vchord_bm25.so"

# vchord_bm25 must be preloaded or CREATE EXTENSION fails outright.
# Baked into CMD rather than left to the deployer: Railway's entrypoint is
# wrapper.sh, and overriding the command at deploy time drops the arguments it
# needs (`-p 5432 -c listen_addresses=*`) and the server never starts.
CMD ["postgres", "-p", "5432", "-c", "listen_addresses=*", \
     "-c", "shared_preload_libraries=vchord_bm25"]

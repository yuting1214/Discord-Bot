# The database this bot needs: Railway's Postgres, plus BM25 and ICU.
#
# The general-purpose version of this image lives in its own repository:
#
#     https://github.com/yuting1214/postgres-search
#
# That one auto-creates its extension set on first boot, ships the analyzer,
# lets a deployer extend shared_preload_libraries, and carries the 13-locale
# verification corpus. None of that belongs in a Discord bot's repository, and
# none of it is needed here: this application applies
# src/backend/search/analyzer.sql itself at startup (see init_db), which creates
# every extension it needs. So this file installs the two that must come from
# the image, and stops.
#
# Kept buildable rather than reduced to a reference, because the database
# service deploys from this directory.
#
# Railway's postgres-ssl is not plain Postgres -- it bundles pgvector,
# pgBackRest backups and the SSL wrapper. Adopting a third-party search image
# would trade all of that away to gain one extension, so the extensions are
# layered on top instead.
#
# VectorChord rather than ParadeDB's pg_search. Not for packaging reasons:
# pg_search does publish Debian packages for this exact base. The reasons are
# licence -- ParadeDB is AGPL-3.0, which many deployers cannot accept -- and
# size, a ~143 MB shared object against roughly 2 MB.
#
# pg_tokenizer is deliberately NOT installed: it costs ~331 MB resident because
# it preloads tokenizer models, and it ranks CJK worse than the analyzer does.

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

# ---- Final stage: Railway's Postgres, plus BM25 and ICU ----
FROM ghcr.io/railwayapp-templates/postgres-ssl:${PG_TAG}

ARG PG_MAJOR
ARG PG_TAG
ARG VCHORD_BM25_VERSION=0.3.0

LABEL org.opencontainers.image.title="postgres-search (Discord-Bot)" \
      org.opencontainers.image.description="Railway postgres-ssl with pgvector, BM25 and ICU segmentation" \
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

# vchord_bm25 must be preloaded or CREATE EXTENSION fails outright.
# Baked into CMD rather than left to the deployer: Railway's entrypoint is
# wrapper.sh, and overriding the command at deploy time drops the arguments it
# needs (`-p 5432 -c listen_addresses=*`) and the server never starts.
CMD ["postgres", "-p", "5432", "-c", "listen_addresses=*", \
     "-c", "shared_preload_libraries=vchord_bm25"]

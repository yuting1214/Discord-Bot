#!/usr/bin/env bash
# The full check, locally, against the database that actually ships.
#
#   ./scripts/ci.sh              lint + SQLite + PostgreSQL + upgrade
#   ./scripts/ci.sh fast         lint + SQLite only, no Docker
#   ./scripts/ci.sh postgres     the PostgreSQL passes only
#
# Why this is not a GitHub Action: it needs the postgres-search image, which is
# built from docker/postgres-search/ in this repository. Building it in a hosted
# runner on every push costs minutes and caching; building it once on a machine
# that already has Docker costs nothing after the first time. Run it before you
# push.
#
# The point of the PostgreSQL passes is that SQLite takes different branches.
# Every production defect this project has had escaped through that gap: the
# lexical tier's zero-score filter, pgvector's `<=>` operator, the analyzer, and
# the bm25 backfill were all unreachable from a SQLite suite.
set -euo pipefail

MODE="${1:-all}"
IMAGE="postgres-search-ci"
CONTAINER="postgres-search-ci"
PORT="${CI_PG_PORT:-55499}"
DSN="postgresql://postgres:ci@localhost:${PORT}/postgres"

cd "$(dirname "$0")/.."

green() { printf "\033[32m%s\033[0m\n" "$*"; }
step()  { printf "\n\033[1m== %s\033[0m\n" "$*"; }

cleanup() {
  if [ "${KEEP_DB:-0}" != "1" ]; then
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  else
    echo "KEEP_DB=1, leaving $CONTAINER on port $PORT"
  fi
}

lint_and_sqlite() {
  step "ruff"
  uv run ruff check .

  step "tests on SQLite"
  uv run pytest -q
}

start_postgres() {
  step "building $IMAGE"
  # Same Dockerfile the database service deploys from, so a change to it is
  # covered by this run rather than discovered on Railway.
  docker build -q -t "$IMAGE" docker/postgres-search >/dev/null

  step "starting PostgreSQL on :$PORT"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$CONTAINER" -p "${PORT}:5432" \
    -e POSTGRES_PASSWORD=ci -e PGDATA=/var/lib/postgresql/data/pgdata \
    "$IMAGE" >/dev/null

  # The image runs a temporary server during first-time init, then restarts it.
  # A query issued in that window fails in a way that looks exactly like a crash.
  for _ in $(seq 1 60); do
    if docker exec "$CONTAINER" pg_isready -U postgres -q 2>/dev/null; then
      sleep 2
      docker exec "$CONTAINER" psql -U postgres -tAc "SELECT 1" >/dev/null 2>&1 && return 0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready; logs follow" >&2
  docker logs "$CONTAINER" >&2
  return 1
}

postgres_passes() {
  start_postgres
  trap cleanup EXIT

  step "tests against PostgreSQL"
  TEST_DATABASE_URL="$DSN" uv run pytest -q -m "not sqlite_only"

  step "upgrade from a v0.1.0-era database"
  TEST_DATABASE_URL="$DSN" uv run python scripts/check_upgrade.py
}

case "$MODE" in
  fast)     lint_and_sqlite ;;
  postgres) postgres_passes ;;
  all)      lint_and_sqlite; postgres_passes ;;
  *) echo "usage: $0 [all|fast|postgres]" >&2; exit 2 ;;
esac

green "
All checks passed."

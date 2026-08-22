#!/usr/bin/env bash
# The full check, locally, against the database that actually ships.
#
#   ./scripts/ci.sh              lint + SQLite + PostgreSQL + upgrade
#   ./scripts/ci.sh fast         lint + SQLite only, no Docker
#   ./scripts/ci.sh postgres     the PostgreSQL passes only
#
# Why this is not a GitHub Action: it pulls and runs a real PostgreSQL, and a
# machine that already has Docker does that in seconds after the first time.
# Run it before you push.
#
# The database is the published image this template deploys, not a local build,
# so these tests run against exactly what a deployer gets.
#
# The point of the PostgreSQL passes is that SQLite takes different branches.
# Every production defect this project has had escaped through that gap: the
# lexical tier's zero-score filter, pgvector's `<=>` operator, the analyzer, and
# the bm25 backfill were all unreachable from a SQLite suite.
set -euo pipefail

MODE="${1:-all}"
# The image behind the PostgreSQL + Hybrid Search template.
IMAGE="${CI_PG_IMAGE:-ghcr.io/yuting1214/postgres-search:0.4.0}"
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
  step "pulling $IMAGE"
  # amd64 only, so Apple Silicon runs it under emulation. Correctness is
  # unaffected; timings and memory readings are not to be trusted there.
  docker pull -q --platform linux/amd64 "$IMAGE" >/dev/null

  step "starting PostgreSQL on :$PORT"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$CONTAINER" -p "${PORT}:5432" --platform linux/amd64 \
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

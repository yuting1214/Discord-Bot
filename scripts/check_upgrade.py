"""Boot the current release against a database shaped like an old one.

An existing deployment does not get a fresh database. It gets the one it already
had, and `create_all` will not touch a table that exists -- so the only thing
standing between a released schema change and a broken deployment is
`_add_missing_columns` and the BM25 backfill.

This builds a v0.1.0-era database by hand -- the tables that release had, with
rows in them, and none of what came later -- then starts the application against
it and asserts the upgrade happened and the old data survived.

    TEST_DATABASE_URL=postgresql://... uv run python scripts/check_upgrade.py

Run against a scratch database: it creates and drops its own schema.
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("upgrade")

DSN = os.getenv("TEST_DATABASE_URL")
if not DSN:
    sys.exit("set TEST_DATABASE_URL to a scratch PostgreSQL running the postgres-search image")

os.environ["ENV_MODE"] = "prod"
os.environ["DATABASE_URL"] = DSN
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

# Exactly the tables v0.1.0 shipped, with the column names it used. No
# search_documents, no summary columns, no bm25 -- that is the point.
LEGACY_SCHEMA = """
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

CREATE TABLE users (
    id uuid PRIMARY KEY,
    discord_id text UNIQUE NOT NULL,
    username text NOT NULL);

CREATE TABLE servers (
    id uuid PRIMARY KEY,
    server_discord_id text UNIQUE NOT NULL,
    server_name text,
    owner_discord_id text NOT NULL);

CREATE TABLE sessions (
    id uuid PRIMARY KEY,
    channel_discord_id text NOT NULL,
    start_time timestamp NOT NULL DEFAULT now(),
    end_time timestamp,
    is_active boolean NOT NULL,
    is_group boolean NOT NULL);

CREATE TABLE user_session_association (
    user_id uuid REFERENCES users(id),
    session_id uuid REFERENCES sessions(id),
    PRIMARY KEY (user_id, session_id));

INSERT INTO users VALUES
    ('11111111-1111-4111-8111-111111111111', 'legacy-user', 'legacy');
INSERT INTO servers VALUES
    ('33333333-3333-4333-8333-333333333333', 'legacy-server', 'Legacy', 'legacy-owner');
INSERT INTO sessions VALUES
    ('22222222-2222-4222-8222-222222222222', 'legacy-channel', now(), NULL, true, false);
INSERT INTO user_session_association VALUES
    ('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222');
"""

# A row as a pre-BM25 release wrote it: the trigger is suppressed, so bm25 stays
# NULL. The lexical tier filters on `bm25 IS NOT NULL`, so without a backfill
# this row is invisible to search for the rest of its life.
LEGACY_DOCUMENT = """
INSERT INTO conversations (id, session_id, start_time)
VALUES ('44444444-4444-4444-8444-444444444444',
        '22222222-2222-4222-8222-222222222222', now());

ALTER TABLE search_documents DISABLE TRIGGER search_documents_bm25;
INSERT INTO search_documents (id, index_key, conversation_id, session_id, content, created_at)
VALUES ('55555555-5555-4555-8555-555555555555', 'legacy-key',
        '44444444-4444-4444-8444-444444444444',
        '22222222-2222-4222-8222-222222222222',
        'sourdough bread from the old release', now());
ALTER TABLE search_documents ENABLE TRIGGER search_documents_bm25;
"""

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        log.info("PASS  %s%s", name, f" -- {detail}" if detail else "")
    else:
        failures.append(f"{name}{f' -- {detail}' if detail else ''}")
        log.error("FAIL  %s%s", name, f" -- {detail}" if detail else "")


async def main() -> int:
    import asyncpg
    from sqlalchemy import text

    raw = await asyncpg.connect(DSN)
    try:
        await raw.execute(LEGACY_SCHEMA)
        before = await raw.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
    finally:
        await raw.close()
    log.info("built a v0.1.0-era database: %d tables", before)

    # Imported here, after the environment is set: importing the application is
    # what registers every model on Base.metadata, and init_db against empty
    # metadata silently creates nothing at all.
    import src.backend.fastapi.main  # noqa: F401
    from src.backend.fastapi.dependencies.database import async_engine, init_db

    await init_db()

    async with async_engine.connect() as c:
        after = (await c.execute(text(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'"))).scalar()
        check("tables were created", after > before, f"{before} -> {after}")

        check("legacy rows survived", (await c.execute(text(
            "SELECT channel_discord_id FROM sessions"))).scalar() == "legacy-channel")

        added = (await c.execute(text(
            "SELECT string_agg(column_name, ',' ORDER BY column_name) "
            "FROM information_schema.columns WHERE table_name='sessions' "
            "AND column_name IN ('summary','summary_vector','summarized_at')"))).scalar()
        check("summary columns added", added == "summarized_at,summary,summary_vector", str(added))

        check("search_documents created", (await c.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name='search_documents'"))).scalar() == 1)

        check("bm25 column attached", (await c.execute(text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='search_documents' AND column_name='bm25'"))).scalar() == 1)

    # Now the backfill, which needs a row that predates the column.
    raw = await asyncpg.connect(DSN)
    try:
        await raw.execute(LEGACY_DOCUMENT)
        unindexed = await raw.fetchval(
            "SELECT count(*) FROM search_documents WHERE bm25 IS NULL")
        check("a pre-BM25 row starts unindexed", unindexed == 1, f"{unindexed} row(s)")
    finally:
        await raw.close()

    await async_engine.dispose()

    # A second boot is what an upgrading deployment actually experiences.
    from importlib import reload

    from src.backend.fastapi.dependencies import database as database_module

    reload(database_module)
    await database_module.init_db()

    raw = await asyncpg.connect(DSN, server_settings={"search_path": "public,bm25_catalog"})
    try:
        indexed = await raw.fetchval(
            "SELECT count(*) FROM search_documents WHERE bm25 IS NOT NULL")
        check("the pre-BM25 row was backfilled", indexed == 1, f"{indexed} row(s)")

        hits = await raw.fetchval("""
            SELECT count(*) FROM search_documents
            WHERE index_key = 'legacy-key' AND bm25 IS NOT NULL
              AND (bm25 <&> bm25_catalog.to_bm25query(
                    'search_documents_bm25_idx',
                    public.to_bm25_query('sourdough'))) < 0""")
        check("and is searchable again", hits == 1, f"{hits} hit(s) for 'sourdough'")
    finally:
        await raw.close()

    await database_module.async_engine.dispose()

    if failures:
        log.error("%d check(s) failed", len(failures))
        return 1
    log.info("upgrade path is clean")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import CreateColumn

from src.backend.fastapi.core.init_settings import global_settings as settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def pool_options_for(url: str) -> dict:
    """Engine pool settings for ``url``.

    SQLite (development) rejects pool sizing arguments, so they are applied only
    where they mean something. Kept a pure function so it can be tested against
    a PostgreSQL URL without reloading this module.
    """
    if url.startswith("sqlite"):
        return {}
    return {
        # pool_size connections are held open for the life of the process and
        # are billed as idle memory; max_overflow connections are opened on
        # demand and closed on return. A low-traffic bot wants a small floor
        # and generous burst headroom, not the default of five permanent.
        "pool_size": 1,
        "max_overflow": 12,
        # Without pre_ping, the first request after an idle night is served on a
        # connection the database has already dropped.
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }


def connect_args_for(url: str) -> dict:
    """Driver options for ``url``.

    vchord_bm25 installs into the `bm25_catalog` schema, and its own functions
    resolve their argument types against the caller's search_path -- so a query
    that fully qualifies `bm25_catalog.to_bm25query(...)` still fails with
    `type "bm25vector" does not exist` unless the schema is on the path. Setting
    it per connection is the only place that covers every session.
    """
    if url.startswith("sqlite"):
        return {}
    return {"server_settings": {"search_path": "public,bm25_catalog"}}


async_engine = create_async_engine(
    settings.ASYNC_DB_URL,
    echo=False,
    connect_args=connect_args_for(settings.ASYNC_DB_URL),
    **pool_options_for(settings.ASYNC_DB_URL),
)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, expire_on_commit=False)


async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session


def _add_missing_columns(connection) -> None:
    """Add columns that exist on the models but not yet in the database.

    ``create_all`` creates missing *tables* and silently leaves existing ones
    alone, so a column added to an already-deployed table never appears. An
    upgrade would then fail on every insert that referenced it.

    Only nullable columns and columns with a default are added, since there is
    no safe value to backfill anything else with. Anything skipped is logged
    rather than passed over quietly.
    """
    if connection.dialect.name == "postgresql":
        # Registers `vector` in the dialect's type map, so reflecting the
        # embedding column below does not emit "Did not recognize type".
        import pgvector.sqlalchemy  # noqa: F401

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all just made it, with every column

        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable and column.default is None and column.server_default is None:
                logger.error(
                    "Cannot add required column %s.%s automatically; it needs a migration",
                    table.name, column.name,
                )
                continue
            ddl = CreateColumn(column).compile(dialect=connection.dialect)
            connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
            logger.info("Added missing column %s.%s", table.name, column.name)


# Ships inside src/ so it is present in the container: the application image
# copies src/ only. It is application-level SQL -- it creates a vocabulary table
# and functions in this schema -- so it belongs with the app, not with the image
# that merely provides the extension.
ANALYZER_SQL = Path(__file__).resolve().parents[2] / "search" / "analyzer.sql"

# BM25 is a PostgreSQL extension. The column is added, populated and indexed
# outside the ORM: the trigger owns the value, so SQLAlchemy never writes it.
_BM25_SETUP = """
ALTER TABLE search_documents ADD COLUMN IF NOT EXISTS bm25 bm25_catalog.bm25vector;

CREATE OR REPLACE FUNCTION search_documents_bm25_trg() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN NEW.bm25 := public.to_bm25(NEW.content); RETURN NEW; END $fn$;

DROP TRIGGER IF EXISTS search_documents_bm25 ON search_documents;
CREATE TRIGGER search_documents_bm25
  BEFORE INSERT OR UPDATE OF content ON search_documents
  FOR EACH ROW EXECUTE FUNCTION search_documents_bm25_trg();

CREATE INDEX IF NOT EXISTS search_documents_bm25_idx
  ON search_documents USING bm25 (bm25 bm25_catalog.bm25_ops);
"""

# Rows that predate the bm25 column keep a NULL, and the lexical tier filters on
# `bm25 IS NOT NULL` -- so an upgrading deployment's entire existing history
# would be invisible to search, silently and permanently. The trigger fires on
# UPDATE OF content, so rewriting the column to itself populates it.
#
# Bounded per startup rather than done in one statement: a large table would
# otherwise hold the boot transaction open long enough to fail the healthcheck.
# Whatever is left is picked up by the next restart.
_BM25_BACKFILL = """
UPDATE search_documents SET content = content
WHERE id IN (SELECT id FROM search_documents WHERE bm25 IS NULL LIMIT 5000)
"""


async def _setup_bm25(conn) -> None:
    """Install the analyzer and attach BM25 to search_documents.

    Best effort: a database without vchord_bm25 still runs, with search falling
    back to the semantic tier alone. That keeps the application deployable
    against a stock PostgreSQL, not only against our own image.
    """
    try:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE"))
    except Exception:
        logger.warning(
            "vchord_bm25 unavailable; lexical search disabled, semantic search unaffected",
            exc_info=True,
        )
        return

    try:
        # Run the scripts through the driver, not through text(): SQLAlchemy
        # reads `::type` casts as bind parameters, and asyncpg's prepared
        # statement path refuses multi-statement scripts. asyncpg's own
        # execute() with no arguments uses the simple query protocol, which
        # handles both, including the dollar-quoted function bodies.
        raw = await conn.get_raw_connection()
        driver = raw.driver_connection
        await driver.execute(ANALYZER_SQL.read_text())
        await driver.execute(_BM25_SETUP)
        logger.info("BM25 lexical search enabled")

        backfilled = await driver.execute(_BM25_BACKFILL)
        # asyncpg returns the command tag, e.g. "UPDATE 42".
        count = int(backfilled.split()[-1]) if backfilled else 0
        if count:
            remaining = await driver.fetchval(
                "SELECT count(*) FROM search_documents WHERE bm25 IS NULL")
            logger.info(
                "Indexed %d pre-existing document(s) for lexical search%s",
                count,
                f"; {remaining} left for the next restart" if remaining else "",
            )
    except Exception:
        logger.warning("Could not attach BM25 to search_documents", exc_info=True)


async def init_db() -> None:
    async with async_engine.begin() as conn:
        # pgvector must exist before create_all: search_documents.embedding is
        # declared as `vector` on PostgreSQL and the DDL fails without it. The
        # extension ships with Railway's postgres-ssl image.
        if async_engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        if async_engine.dialect.name == "postgresql":
            await _setup_bm25(conn)

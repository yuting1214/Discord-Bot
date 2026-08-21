import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.schema import CreateColumn

from src.backend.fastapi.core.init_settings import global_settings as settings

logger = logging.getLogger(__name__)

# Base class for the database models
Base = declarative_base()

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


_pool_options = pool_options_for(settings.ASYNC_DB_URL)

async_engine = create_async_engine(
    settings.ASYNC_DB_URL, echo=False, future=True, **_pool_options
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, expire_on_commit=False, class_=AsyncSession
)


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


async def init_db():
    # pgvector must exist before create_all: search_documents.embedding is
    # declared as `vector` on PostgreSQL and the DDL fails without it. The
    # extension ships with Railway's postgres-ssl image, so this only enables it.
    async with async_engine.begin() as conn:
        if async_engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

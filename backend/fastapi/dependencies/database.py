from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from backend.fastapi.core.init_settings import global_settings as settings

# Base class for the database models
Base = declarative_base()

# SQLite (development) rejects pool sizing arguments, so they are applied only
# where they mean something.
_pool_options = {}
if not settings.ASYNC_DB_URL.startswith("sqlite"):
    _pool_options = {
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

async_engine = create_async_engine(
    settings.ASYNC_DB_URL, echo=False, future=True, **_pool_options
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, expire_on_commit=False, class_=AsyncSession
)


async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    # pgvector must exist before create_all: search_documents.embedding is
    # declared as `vector` on PostgreSQL and the DDL fails without it. The
    # extension ships with Railway's postgres-ssl image, so this only enables it.
    async with async_engine.begin() as conn:
        if async_engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

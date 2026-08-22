import os

# Settings require an API key at import time; the tests never call a provider.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing the package registers every model on Base.metadata.
import src.backend.fastapi.models  # noqa: F401
from src.backend.data.discord_command import command_data
from src.backend.fastapi.dependencies.database import Base, get_async_db
from src.backend.fastapi.main import app
from src.backend.fastapi.models import LLM, Command

# Set to a scratch PostgreSQL and the whole suite runs there instead of SQLite.
# This is not a nicety: SQLite takes different branches. Every production defect
# this project has had lived in a branch SQLite never executes -- the lexical
# tier's zero-score filter, pgvector's `<=>`, the analyzer, the bm25 backfill.
# ./scripts/ci.sh runs both.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """A real database, per test, on the async engine the app uses."""
    if TEST_DATABASE_URL:
        engine, schema = await _postgres_engine()
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'test.db'}")
        schema = None

    async with engine.begin() as conn:
        if schema is None:
            await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    # Seed the rows the bot expects to find rather than create.
    async with factory() as db:
        async with db.begin():
            for command in command_data:
                db.add(Command(**command))
            db.add(
                LLM(
                    llm_model_name="Test Model",
                    llm_vendor="OpenAI",
                    api_provider="OpenRouter",
                    api_endpoint="openai/gpt-5.6-luna",
                )
            )

    yield factory
    await engine.dispose()
    if schema is not None:
        await _drop_schema(schema)


async def _postgres_engine():
    """An engine on a schema of its own, so tests cannot see each other's rows.

    A shared database with TRUNCATE between tests leaks through sequences and
    through anything the analyzer writes; a private schema does not.
    """
    import uuid as _uuid

    from sqlalchemy import text as _text

    from src.backend.fastapi.dependencies.database import connect_args_for

    url = TEST_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    schema = f"t{_uuid.uuid4().hex[:12]}"

    admin = create_async_engine(url, connect_args=connect_args_for(url))
    async with admin.begin() as conn:
        await conn.execute(_text(f"CREATE SCHEMA {schema}"))
    await admin.dispose()

    # bm25_catalog stays on the path: vchord's operators resolve their argument
    # types against it, and a fully qualified call still fails without it.
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": f"{schema},public,bm25_catalog"}}
    )
    # The same sequence init_db runs, deliberately: this repository's database
    # image ships only the shared objects, and it is the application that
    # creates the extensions and installs the analyzer. Doing it here means the
    # tests exercise that path rather than assuming someone else ran it.
    from src.backend.fastapi.dependencies.database import _setup_bm25

    async with engine.begin() as conn:
        await conn.execute(_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await _setup_bm25(conn)
    return engine, schema


async def _drop_schema(schema: str) -> None:
    from sqlalchemy import text as _text

    url = TEST_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    admin = create_async_engine(url)
    async with admin.begin() as conn:
        await conn.execute(_text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    await admin.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    """An in-process HTTP client on the *test's* event loop.

    Not TestClient. That runs the app on an event loop of its own, and asyncpg
    binds a pooled connection to the loop that created it -- so against
    PostgreSQL every request failed with the connection unavailable, while
    SQLite happily served both loops and hid it.
    """

    async def override():
        async with session_factory() as db:
            yield db

    app.dependency_overrides[get_async_db] = override
    # No lifespan: it would create the real dev database and start the bot.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def toy_embedding(text: str) -> list[float]:
    """A deterministic stand-in for a provider embedding.

    Sized to the configured dimension, not to 26. SQLite stores the vector as
    JSON and accepts any length; PostgreSQL declares `vector(n)` and rejects a
    mismatch outright, so a short stub passes the whole suite and fails on the
    database that ships.

    Note it is a bag of characters, so everything lands near everything else --
    fine for "did this rank at all", useless for testing a distance threshold.
    """
    from src.backend.search.embeddings import EMBEDDING_DIM

    vector = [0.0] * EMBEDDING_DIM
    for character in text.lower():
        if "a" <= character <= "z":
            vector[(ord(character) - 97) % EMBEDDING_DIM] += 1.0
    return vector

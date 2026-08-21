import os

# Settings require an API key at import time; the tests never call a provider.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Importing the package registers every model on Base.metadata.
import backend.fastapi.models  # noqa: F401
from backend.data.discord_command import command_data
from backend.fastapi.dependencies.database import Base
from backend.fastapi.models import LLM, Command


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    """A real database, per test, on the async engine the app uses."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'test.db'}")
    async with engine.begin() as conn:
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


@pytest.fixture
def anyio_backend():
    return "asyncio"

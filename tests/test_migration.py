"""The upgrade path for already-deployed databases.

`create_all` creates missing tables and leaves existing ones untouched, so a
column added to a table that is already deployed never appears. With 62 live
deployments receiving auto-updates, that would mean a bot which fails on every
message it tries to store.
"""

import asyncio

import pytest
from sqlalchemy import Column, String, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.backend.fastapi.dependencies.database import Base, _add_missing_columns
from src.backend.fastapi.models import Message

pytestmark = pytest.mark.asyncio


async def _columns(engine, table: str) -> set[str]:
    async with engine.connect() as conn:
        return set(
            await conn.run_sync(
                lambda c: {col["name"] for col in inspect(c).get_columns(table)}
            )
        )


async def test_a_column_added_to_an_existing_table_is_backfilled(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'up.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Simulate the deployed v0.1.0 schema, which predates the column.
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE messages DROP COLUMN reasoning_details"))
    assert "reasoning_details" not in await _columns(engine, "messages")

    # What an upgrading container runs on boot.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

    assert "reasoning_details" in await _columns(engine, "messages")
    await engine.dispose()


async def test_reconciliation_is_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'idem.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    before = await _columns(engine, "messages")

    for _ in range(3):
        async with engine.begin() as conn:
            await conn.run_sync(_add_missing_columns)

    assert await _columns(engine, "messages") == before
    await engine.dispose()


async def test_a_required_column_is_reported_not_guessed(tmp_path, caplog):
    """There is no safe value to backfill a NOT NULL column with, so it must be
    logged as needing a migration rather than added with an invented default."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'req.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Message.__table__.append_column(Column("mandatory_field", String, nullable=False))
    try:
        with caplog.at_level("ERROR"):
            async with engine.begin() as conn:
                await conn.run_sync(_add_missing_columns)
        assert "mandatory_field" in caplog.text
        assert "migration" in caplog.text
        assert "mandatory_field" not in await _columns(engine, "messages")
    finally:
        Message.__table__._columns.remove(Message.__table__.c.mandatory_field)
    await engine.dispose()


async def test_startup_waits_for_the_database_to_appear(monkeypatch, caplog):
    """Private networking is not up the instant a container starts.

    On Railway the database is reached over *.railway.internal, which does not
    resolve for the first moment of a container's life. Connecting immediately
    raised "Name or service not known" and the app exited -- on a healthy
    deployment. Observed on a real deploy before this retry existed.
    """
    from src.backend.fastapi.dependencies import database

    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError(-2, "Name or service not known")

    monkeypatch.setattr(database, "_prepare_schema", flaky)
    # database.asyncio IS the asyncio module, so capture the real sleep first
    # or the replacement calls itself.
    real_sleep = asyncio.sleep
    monkeypatch.setattr(database.asyncio, "sleep", lambda _: real_sleep(0))

    with caplog.at_level("WARNING"):
        await database.init_db()

    assert attempts["n"] == 3, "should have retried until it succeeded"
    assert "not reachable yet" in caplog.text


async def test_startup_gives_up_on_a_database_that_never_appears(monkeypatch):
    """A genuinely misconfigured database must not be retried forever."""
    from src.backend.fastapi.dependencies import database

    async def never():
        raise OSError(-2, "Name or service not known")

    monkeypatch.setattr(database, "_prepare_schema", never)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(database.asyncio, "sleep", lambda _: real_sleep(0))

    with pytest.raises(OSError):
        await database.init_db(max_wait=2.0)


async def test_a_real_error_is_not_swallowed_by_the_retry(monkeypatch):
    """Only connection-shaped failures are retried; a bug should surface."""
    from src.backend.fastapi.dependencies import database

    async def bug():
        raise ValueError("a genuine programming error")

    monkeypatch.setattr(database, "_prepare_schema", bug)
    with pytest.raises(ValueError):
        await database.init_db()

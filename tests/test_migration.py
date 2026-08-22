"""The upgrade path for already-deployed databases.

`create_all` creates missing tables and leaves existing ones untouched, so a
column added to a table that is already deployed never appears. With 62 live
deployments receiving auto-updates, that would mean a bot which fails on every
message it tries to store.
"""


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


def test_the_analyzer_sql_ships_with_the_application():
    """It must live under src/: the container image copies src/ and nothing else,
    so a path outside it resolves locally and is missing in production."""
    from src.backend.fastapi.dependencies.database import ANALYZER_SQL

    assert ANALYZER_SQL.exists(), ANALYZER_SQL
    assert "src" in ANALYZER_SQL.parts, "must be inside src/ to reach the image"
    body = ANALYZER_SQL.read_text()
    for expected in ("bm25_vocabulary", "to_bm25", "to_bm25_query", "bm25_terms"):
        assert expected in body, expected

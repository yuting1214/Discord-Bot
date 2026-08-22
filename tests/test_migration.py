"""The upgrade path for already-deployed databases.

`create_all` creates missing tables and leaves existing ones untouched, so a
column added to a table that is already deployed never appears. With 62 live
deployments receiving auto-updates, that would mean a bot which fails on every
message it tries to store.
"""


import re

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


def test_high_cardinality_token_types_stay_out_of_the_vocabulary():
    """vchord_bm25 spends ~8KB of index per distinct term regardless of how many
    documents contain it, so ids, hashes and URLs are the dominant cost on chat
    data. Measured on 20,000 chat-shaped rows: 641MB of index and 81,714 terms
    with these mappings present, 736KB and 15 terms without them.
    """
    from src.backend.fastapi.dependencies.database import ANALYZER_SQL

    body = ANALYZER_SQL.read_text()
    mapping_drop = body.split("DROP MAPPING IF EXISTS FOR", 1)
    assert len(mapping_drop) == 2, "the token-type mappings are no longer dropped"
    dropped = mapping_drop[1].split(";", 1)[0]
    for token_type in ("numword", "uint", "int", "url", "url_path", "file", "version"):
        assert token_type in dropped, token_type


# Codepoint, not character: U+8C48 and U+F900 render identically, and pasting
# the wrong one silently folded the whole Hangul block into the han range.
UNSPACED_SCRIPTS = {
    "han": {"CJK ext A": 0x3400, "CJK": 0x4E00, "CJK compatibility": 0xF900,
            "CJK ext B": 0x20000},
    "kana": {"hiragana": 0x3042, "katakana": 0x30A2, "katakana phonetic": 0x31F0,
             "halfwidth katakana": 0xFF66, "halfwidth voiced mark": 0xFF9F},
    "hangul": {"syllables": 0xAC00, "compatibility jamo": 0x3130},
    "th": {"Thai": 0x0E01},
    "lo": {"Lao": 0x0E81},
    "km": {"Khmer": 0x1780},
    "my": {"Myanmar": 0x1000},
}


def _class_ranges(body: str, script: str) -> list[tuple[int, int]]:
    """The \\U ranges the analyzer assigns to one script."""
    start = body.index("ELSE '[") if script == "all" else body.index(f"WHEN '{script}'")
    end = body.index("]'", start)
    return [
        (int(lo, 16), int(hi, 16))
        for lo, hi in re.findall(r"\\U([0-9A-F]{8})-\\U([0-9A-F]{8})", body[start:end])
    ]


@pytest.mark.parametrize("script", sorted(UNSPACED_SCRIPTS))
def test_each_unspaced_script_is_classified_and_only_it(script):
    """Scripts to_tsvector cannot segment must reach a segmenter, and must reach
    the right one. Neither failure is loud: a script missing from the union
    becomes one token per phrase, and a script leaking into another's range is
    tokenized twice, once by each.
    """
    from src.backend.fastapi.dependencies.database import ANALYZER_SQL

    body = ANALYZER_SQL.read_text()
    mine = _class_ranges(body, script)
    union = _class_ranges(body, "all")

    for name, codepoint in UNSPACED_SCRIPTS[script].items():
        assert any(lo <= codepoint <= hi for lo, hi in mine), f"{name} missing from {script}"
        assert any(lo <= codepoint <= hi for lo, hi in union), f"{name} missing from the union"
        for other in UNSPACED_SCRIPTS:
            if other == script:
                continue
            assert not any(
                lo <= codepoint <= hi for lo, hi in _class_ranges(body, other)
            ), f"{name} also matches the {other} range"


def test_the_database_image_ships_the_same_analyzer():
    """The image and the application need the same file for opposite reasons --
    the image's build context is its own directory and cannot reach into src/,
    and the application image copies src/ and nothing else. Neither can be a
    symlink to the other, so the copy is checked instead: a drift here means the
    standalone database segments text differently from the bot that queries it.
    """
    from src.backend.fastapi.dependencies.database import ANALYZER_SQL

    shipped = ANALYZER_SQL.parents[3] / "docker" / "postgres-bm25" / "analyzer.sql"
    assert shipped.exists(), shipped
    assert shipped.read_bytes() == ANALYZER_SQL.read_bytes(), (
        f"cp {ANALYZER_SQL} {shipped}"
    )

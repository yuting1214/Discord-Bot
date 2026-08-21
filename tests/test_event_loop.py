"""The bot and the web application must share one event loop.

They used to run on two: uvicorn in a background thread, discord.py in the main
thread. Both halves use the same SQLAlchemy engine, so once the bot began
talking to the database directly, a connection pooled on one loop was checked
out on the other and asyncpg failed with:

    RuntimeError: ... got Future <Future pending> attached to a different loop

Every slash command failed in production while every test passed, because the
tests drove the database from a single-loop process and never started the bot.
"""

import ast
import asyncio
import inspect
import textwrap

import pytest

from src.backend.discord import register
from src.backend.fastapi import main


class FakeClient:
    def __init__(self):
        self._closed = False

    def is_closed(self):
        return self._closed

    async def close(self):
        self._closed = True


@pytest.mark.asyncio
async def test_the_bot_runs_on_the_applications_event_loop(monkeypatch):
    seen = {}
    fake = FakeClient()

    async def fake_run(client):
        seen["loop"] = asyncio.get_running_loop()
        seen["client"] = client
        await asyncio.sleep(3600)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(main, "build_client", lambda: fake)
    monkeypatch.setattr(main, "run_discord_bot", fake_run)
    monkeypatch.setattr(main, "init_db", noop)
    monkeypatch.setattr(main, "log_credentials_once", lambda: None)
    monkeypatch.setattr(main, "create_init_command_async", noop)
    monkeypatch.setattr(main, "async_engine", type("E", (), {"dispose": noop})())

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def close(self): return None
    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: FakeSession())

    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert seen["loop"] is asyncio.get_running_loop(), (
            "the bot must run on the application's loop, not one of its own"
        )
        assert seen["client"] is fake

    assert fake.is_closed(), "the client should be closed on shutdown"


def test_the_bot_is_started_not_run():
    """client.run() builds its own event loop; client.start() uses the caller's."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(register.run_discord_bot)))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "start" in called, called
    assert "run" not in called, called


def test_the_entrypoint_spawns_no_thread():
    source = inspect.getsource(main)
    assert "Thread(" not in source, "a second thread means a second event loop"
    assert "threading" not in source

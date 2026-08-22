"""Session summarisation: one embedding per session instead of one per turn.

The change this covers is an economic one. Every user message used to be
embedded as it arrived -- O(turns) provider calls on the hot path of every
command -- and most turns do not deserve one. These tests assert both halves:
that the per-turn call is gone, and that the summary that replaces it is
actually produced, embedded, and reachable by search.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from src.backend.constants import utcnow
from src.backend.discord import run_async
from src.backend.discord import service as discord_service
from src.backend.fastapi.models import SearchDocument, Session
from src.backend.search import service as search_service
from src.backend.search import summary as summary_module
from src.llm.chat import ChatResult

CTX = {
    "server_discord_id": "server-1",
    "server_name": "server",
    "owner_discord_id": "owner-1",
    "channel_discord_id": "channel-1",
    "channel_name": "general",
    "user_discord_id": "user-1",
    "user_name": "someone",
}


def _toy_embedding(text: str) -> list[float]:
    vector = [0.0] * 26
    for character in text.lower():
        if "a" <= character <= "z":
            vector[ord(character) - 97] += 1.0
    return vector or [0.0] * 26


@pytest.fixture(autouse=True)
def wire(monkeypatch, session_factory):
    monkeypatch.setattr(run_async, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(summary_module, "AsyncSessionLocal", session_factory)

    async def fake_embed(text):
        return _toy_embedding(text)

    monkeypatch.setattr(search_service, "embed", fake_embed)
    monkeypatch.setattr(summary_module, "embed", fake_embed)
    monkeypatch.setattr(run_async, "schedule_summary", lambda session_id: None)
    return session_factory


async def stub_chat(text="a reply"):
    async def _chat(*a, **k):
        return ChatResult(text=text, model="stub", input_tokens=1, output_tokens=1)

    return _chat


async def seed(wire, monkeypatch, texts, *, new_session=True):
    """Run real turns through the command layer and return the session id."""
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    for i, text in enumerate(texts):
        await run_async.complete_session_chat(
            **CTX, user_input=text, is_group=False, is_new_session=new_session and i == 0
        )
    async with wire() as db:
        # The active one: starting a new session deactivates the previous, and
        # start_time ties at SQLite's resolution so it cannot order them.
        return (await db.execute(
            select(Session.id).where(Session.is_active.is_(True))
        )).scalars().first()


async def test_no_turn_is_embedded_any_more(wire, monkeypatch):
    """The reason this work exists: the provider call per message is gone."""
    calls = []

    async def counting_embed(text):
        calls.append(text)
        return _toy_embedding(text)

    monkeypatch.setattr(search_service, "embed", counting_embed)
    monkeypatch.setattr(summary_module, "embed", counting_embed)

    await seed(wire, monkeypatch, ["one", "two", "three"])

    assert calls == [], f"expected no embedding calls during chat, got {calls}"
    async with wire() as db:
        docs = (await db.execute(select(SearchDocument))).scalars().all()
    assert len(docs) == 3, "every message is still indexed for lexical search"
    assert all(d.embedding is None for d in docs)


async def test_a_summary_is_written_and_embedded(wire, monkeypatch):
    session_id = await seed(wire, monkeypatch, ["how do i bake sourdough", "what hydration"])
    monkeypatch.setattr(summary_module, "achat", await stub_chat("A chat about sourdough hydration."))

    async with wire() as db:
        async with db.begin():
            summary = await summary_module.summarize_session(db, session_id)

    assert summary == "A chat about sourdough hydration."
    async with wire() as db:
        session = await db.get(Session, session_id)
    assert session.summary == summary
    assert session.summary_vector, "the summary is what gets embedded now"
    assert session.summarized_at is not None


async def test_one_summary_per_session_not_one_per_turn(wire, monkeypatch):
    """The whole economic argument, asserted: turns grow, embeddings do not."""
    session_id = await seed(wire, monkeypatch, ["one", "two", "three", "four", "five"])
    embeds = []

    async def counting_embed(text):
        embeds.append(text)
        return _toy_embedding(text)

    monkeypatch.setattr(summary_module, "embed", counting_embed)
    monkeypatch.setattr(summary_module, "achat", await stub_chat("A summary."))

    async with wire() as db:
        async with db.begin():
            await summary_module.summarize_session(db, session_id)

    assert len(embeds) == 1, "five turns, one embedding"


async def test_an_already_summarised_session_is_not_paid_for_twice(wire, monkeypatch):
    """Closing a session and the sweep can race. Two calls, one bill."""
    session_id = await seed(wire, monkeypatch, ["one", "two"])
    calls = []

    async def counting_chat(*a, **k):
        calls.append(1)
        return ChatResult(text="A summary.", model="stub", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(summary_module, "achat", counting_chat)

    for _ in range(3):
        async with wire() as db:
            async with db.begin():
                await summary_module.summarize_session(db, session_id)

    assert len(calls) == 1

    async with wire() as db:
        async with db.begin():
            await summary_module.summarize_session(db, session_id, force=True)
    assert len(calls) == 2, "force is the escape hatch for retrying a bad summary"


async def test_a_session_too_short_to_summarise_is_not_retried_forever(wire, monkeypatch):
    """A one-message session has nothing to summarise, but must still be marked
    done or every sweep for the rest of time will look at it again."""
    session_id = await seed(wire, monkeypatch, ["hello"])

    async with wire() as db:
        async with db.begin():
            # One user turn plus one model reply is the floor; drop the reply.
            from src.backend.fastapi.models import Message

            messages = (await db.execute(select(Message))).scalars().all()
            for message in messages[1:]:
                await db.delete(message)

    calls = []

    async def counting_chat(*a, **k):
        calls.append(1)
        return ChatResult(text="x", model="stub", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(summary_module, "achat", counting_chat)
    async with wire() as db:
        async with db.begin():
            assert await summary_module.summarize_session(db, session_id) is None

    assert calls == [], "no provider call for a session with nothing in it"
    async with wire() as db:
        assert (await db.get(Session, session_id)).summarized_at is not None


async def test_the_sweep_picks_up_a_session_nobody_closed(wire, monkeypatch):
    """A user who stops replying leaves a session active forever. Without the
    sweep it is never summarised and never semantically searchable."""
    session_id = await seed(wire, monkeypatch, ["one", "two"])
    monkeypatch.setattr(summary_module, "achat", await stub_chat("A summary."))

    async with wire() as db:
        async with db.begin():
            session = await db.get(Session, session_id)
            assert session.is_active, "still open: nothing closed it"
            session.start_time = utcnow() - timedelta(days=1)

    async with wire() as db:
        async with db.begin():
            summarised = await summary_module.summarize_idle_sessions(db)

    assert summarised == 1
    async with wire() as db:
        assert (await db.get(Session, session_id)).summary == "A summary."


async def test_the_sweep_leaves_a_still_active_session_alone(wire, monkeypatch):
    session_id = await seed(wire, monkeypatch, ["one", "two"])
    monkeypatch.setattr(summary_module, "achat", await stub_chat("A summary."))

    async with wire() as db:
        async with db.begin():
            assert await summary_module.summarize_idle_sessions(db) == 0
    async with wire() as db:
        assert (await db.get(Session, session_id)).summarized_at is None


async def test_one_bad_session_does_not_stop_the_batch(wire, monkeypatch):
    """A sweep that aborts on the first failure never reaches the rest."""
    first = await seed(wire, monkeypatch, ["one", "two"])
    second = await seed(wire, monkeypatch, ["three", "four"], new_session=True)
    assert first != second

    calls = []

    async def flaky_chat(transcript, *a, **k):
        calls.append(transcript)
        if len(calls) == 1:
            raise RuntimeError("provider is down")
        return ChatResult(text="A summary.", model="stub", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(summary_module, "achat", flaky_chat)
    async with wire() as db:
        async with db.begin():
            for session_id in (first, second):
                session = await db.get(Session, session_id)
                session.start_time = utcnow() - timedelta(days=1)

    async with wire() as db:
        async with db.begin():
            summarised = await summary_module.summarize_idle_sessions(db)

    assert len(calls) == 2, "it kept going after the failure"
    assert summarised == 1


async def test_a_failed_summary_is_left_for_the_next_sweep(wire, monkeypatch):
    """summarized_at must stay NULL, or the retry never happens."""
    session_id = await seed(wire, monkeypatch, ["one", "two"])
    monkeypatch.setattr(summary_module, "achat", await stub_chat("   "))

    async with wire() as db:
        async with db.begin():
            assert await summary_module.summarize_session(db, session_id) is None
    async with wire() as db:
        assert (await db.get(Session, session_id)).summarized_at is None


async def test_search_finds_a_session_by_its_summary(wire, monkeypatch):
    """The point of the semantic tier: a query that shares no word with any
    message still finds the session, through the summary."""
    session_id = await seed(wire, monkeypatch, ["zzz qqq", "wwww vvvv"])
    monkeypatch.setattr(summary_module, "achat", await stub_chat("sourdough bread baking"))

    async with wire() as db:
        async with db.begin():
            await summary_module.summarize_session(db, session_id)

    async with wire() as db:
        index_key = (await db.execute(select(SearchDocument.index_key))).scalars().first()
        results = await search_service.hybrid_search(db, index_key, "sourdough bread baking")

    assert results, "the summary should be reachable even though no message matches"


async def test_closing_a_session_schedules_its_summary(wire, monkeypatch):
    """manage_session has to report what it closed, or nothing ever triggers."""
    await seed(wire, monkeypatch, ["one"])

    closed: list = []
    async with wire() as db:
        async with db.begin():
            user = await discord_service.get_or_create_user(db, "user-1", "someone")
            await discord_service.manage_session(
                db, "channel-1", user, False, True, closed
            )

    assert len(closed) == 1, "the previous session was closed and reported"

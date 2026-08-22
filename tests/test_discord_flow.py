"""End-to-end coverage of the bot's command flow against a real database.

These exercise the path that replaced the self-HTTP tier: the bot now talks to
the database directly, inside transactions, so the things worth proving are that
records land, that memory replays correctly across turns, and that a failure
rolls the whole turn back rather than leaving half a conversation behind.
"""


import pytest
from sqlalchemy import func, select

from src.backend.discord import run_async, service
from src.backend.fastapi.models import (
    Channel,
    CommandLog,
    Conversation,
    LLMUsage,
    Message,
    SearchDocument,
    Server,
    Session,
    User,
)
from src.backend.search import service as search_service
from src.llm.chat import ChatResult

pytestmark = pytest.mark.asyncio

CTX = dict(
    server_discord_id="server-1",
    server_name="Test Server",
    owner_discord_id="owner-1",
    channel_discord_id="channel-1",
    channel_name="general",
    user_discord_id="user-1",
    user_name="tester",
)

REASONING = [{"type": "reasoning.text", "text": "thinking"}]


@pytest.fixture(autouse=True)
def wire(monkeypatch, session_factory):
    """Point the command layer at the test database and stub the network."""
    monkeypatch.setattr(run_async, "AsyncSessionLocal", session_factory)

    async def noop(*a, **k):
        return {}

    # No provider call in tests: embeddings are deterministic stand-ins.
    async def fake_embed(text):
        return _toy_embedding(text)

    monkeypatch.setattr(run_async, "embed", fake_embed)
    monkeypatch.setattr(search_service, "embed", fake_embed)
    return session_factory


def _toy_embedding(text: str) -> list[float]:
    """A tiny bag-of-characters vector: similar strings point similar ways."""
    vector = [0.0] * 26
    for character in text.lower():
        if "a" <= character <= "z":
            vector[ord(character) - 97] += 1.0
    return vector or [0.0] * 26


async def count(factory, model) -> int:
    async with factory() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar()


async def stub_chat(text="Hello there.", reasoning=REASONING, model="openai/gpt-5.6-luna"):
    async def _chat(user_input, memory=None, **kwargs):
        _chat.calls.append({"user_input": user_input, "memory": memory})
        return ChatResult(
            text=text, model=model, input_tokens=11, output_tokens=4,
            reasoning_details=reasoning,
        )
    _chat.calls = []
    return _chat


async def test_new_session_persists_the_whole_turn(wire, monkeypatch):
    chat = await stub_chat()
    monkeypatch.setattr(run_async, "achat", chat)

    result = await run_async.complete_session_chat(
        **CTX, user_input="Hi", is_group=False, is_new_session=True
    )

    assert result == {"llm_response": "Hello there."}, result
    for model, expected in ((User, 1), (Server, 1), (Channel, 1), (Session, 1),
                            (Conversation, 1), (Message, 2), (CommandLog, 1), (LLMUsage, 1)):
        assert await count(wire, model) == expected, model.__name__

    async with wire() as db:
        rows = (await db.execute(select(Message).order_by(Message.message_type))).scalars().all()
        by_type = {m.message_type: m for m in rows}
        assert by_type["user"].content == "Hi"
        assert by_type["user"].reasoning_details is None, "user turns must not store a trace"
        assert by_type["model"].content == "Hello there."
        assert by_type["model"].reasoning_details == REASONING

        usage = (await db.execute(select(LLMUsage))).scalars().first()
        assert (usage.input_tokens, usage.output_tokens) == (11, 4)

        conversation = (await db.execute(select(Conversation))).scalars().first()
        assert conversation.end_time is not None, "conversation should be closed out"


async def test_second_turn_replays_the_reasoning_trace(wire, monkeypatch):
    chat = await stub_chat()
    monkeypatch.setattr(run_async, "achat", chat)

    await run_async.complete_session_chat(**CTX, user_input="Hi", is_group=False, is_new_session=True)
    await run_async.complete_session_chat(**CTX, user_input="Again", is_group=False, is_new_session=False)

    # Turn two must carry turn one's assistant trace back, unmodified.
    memory = chat.calls[1]["memory"]
    assistant = [m for m in memory if m["role"] == "assistant"]
    assert assistant, f"no assistant turn replayed: {memory}"
    assert assistant[0]["reasoning_details"] == REASONING
    assert all("reasoning_details" not in m for m in memory if m["role"] == "user")

    # Continuing must reuse the session, not start a new one.
    assert await count(wire, Session) == 1
    assert await count(wire, Conversation) == 2


async def test_new_session_deactivates_the_previous_one(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())

    await run_async.complete_session_chat(**CTX, user_input="one", is_group=False, is_new_session=True)
    await run_async.complete_session_chat(**CTX, user_input="two", is_group=False, is_new_session=True)

    async with wire() as db:
        sessions = (await db.execute(select(Session).order_by(Session.start_time))).scalars().all()
    assert len(sessions) == 2
    assert [s.is_active for s in sessions] == [False, True]
    assert sessions[0].end_time is not None


async def test_provider_failure_rolls_the_turn_back(wire, monkeypatch):
    """The user message is committed before the call, so a failure must not
    leave a dangling model message or a closed conversation."""
    async def boom(*a, **k):
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(run_async, "achat", boom)

    result = await run_async.complete_session_chat(
        **CTX, user_input="Hi", is_group=False, is_new_session=True
    )

    assert "error" in result and "provider exploded" in result["error"]
    assert await count(wire, Message) == 1, "only the user turn should exist"
    assert await count(wire, LLMUsage) == 0
    async with wire() as db:
        conversation = (await db.execute(select(Conversation))).scalars().first()
    assert conversation.end_time is None, "conversation must stay open on failure"


async def test_group_and_single_sessions_are_isolated(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())

    await run_async.complete_session_chat(**CTX, user_input="solo", is_group=False, is_new_session=True)
    await run_async.complete_session_chat(**CTX, user_input="group", is_group=True, is_new_session=True)

    async with wire() as db:
        sessions = (await db.execute(select(Session))).scalars().all()
        channels = (await db.execute(select(Channel))).scalars().all()
    assert sorted(s.is_group for s in sessions) == [False, True]
    assert all(s.is_active for s in sessions), "one must not deactivate the other"
    assert sorted(c.is_group for c in channels) == [False, True]


async def test_resume_reactivates_a_named_session(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())

    await run_async.complete_session_chat(**CTX, user_input="one", is_group=False, is_new_session=True)
    async with wire() as db:
        first = (await db.execute(select(Session))).scalars().first()
        first_id = str(first.id)
    await run_async.complete_session_chat(**CTX, user_input="two", is_group=False, is_new_session=True)

    result = await run_async.resume_session(**CTX, user_input=f"resume {first_id}", is_group=False)
    assert "has resumed" in result["message"], result

    async with wire() as db:
        resumed = (await db.execute(select(Session).where(Session.id == first.id))).scalars().first()
        others = (await db.execute(select(Session).where(Session.id != first.id))).scalars().all()
    assert resumed.is_active and resumed.end_time is None
    assert all(not s.is_active for s in others), "the other session should be stood down"


async def test_resume_rejects_bad_input(wire):
    """A rejection must say what a valid input looks like and where to get one."""
    bad = (await run_async.resume_session(**CTX, user_input="nonsense", is_group=False))["message"]
    assert "session ID" in bad
    assert "/search" in bad, "must point at the command that lists session ids"

    missing = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    gone = (await run_async.resume_session(**CTX, user_input=missing, is_group=False))["message"]
    assert "No session with ID" in gone
    assert missing in gone, "echo the id so the user can see what was tried"
    assert "/search" in gone

    # Browser testing found these two returning byte-identical text, because a
    # UUID4-only pattern rejected the nil UUID before any lookup happened. A
    # user pasting a valid id for a deleted session was told it was malformed.
    nil = "00000000-0000-0000-0000-000000000000"
    unknown = (await run_async.resume_session(**CTX, user_input=nil, is_group=False))["message"]
    assert unknown != bad, "a well-formed unknown id is not the same failure as garbage"
    assert nil in unknown, "it reached the lookup rather than being rejected on shape"


async def test_repeat_user_does_not_duplicate_records(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    for _ in range(3):
        await run_async.complete_session_chat(
            **CTX, user_input="hi", is_group=False, is_new_session=False
        )
    assert await count(wire, User) == 1
    assert await count(wire, Server) == 1
    assert await count(wire, Channel) == 1
    assert await count(wire, Session) == 1, "an ongoing session should be reused"


async def test_search_accepts_string_ids_from_the_index(wire, monkeypatch):
    """The search index returns conversation ids as strings, but the column is
    typed UUID -- the two must not be compared directly."""
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    await run_async.complete_session_chat(**CTX, user_input="hi", is_group=False, is_new_session=True)

    async with wire() as db:
        conversation = (await db.execute(select(Conversation))).scalars().first()
        as_string = str(conversation.id)

        rows = await service.get_messages_by_conversations(db, [as_string])
    assert len(rows) == 2, rows
    assert {r["message_type"] for r in rows} == {"user", "model"}

    async with wire() as db:
        assert await service.get_messages_by_conversations(db, []) == []


async def test_resume_tolerates_a_malformed_uuid(wire):
    async with wire() as db:
        assert await service.get_session_if_exists(db, "not-a-uuid") is None


async def test_messages_are_indexed_for_search(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    await run_async.complete_session_chat(
        **CTX, user_input="the capital of france", is_group=False, is_new_session=True
    )

    async with wire() as db:
        docs = (await db.execute(select(SearchDocument))).scalars().all()
    assert len(docs) == 1
    assert docs[0].content == "the capital of france"
    assert docs[0].embedding, "embedding should be stored"


async def test_search_ranks_the_relevant_conversation_first(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    for text in ("how do i bake sourdough bread", "what is the capital of france"):
        await run_async.complete_session_chat(
            **CTX, user_input=text, is_group=False, is_new_session=False
        )

    result = await run_async.search_messages_and_list_sessions(
        **CTX, user_input="capital of france", is_group=False
    )
    message = result["message"]
    assert "what is the capital of france" in message, message
    # The rendered output must carry a session id and say how to use it,
    # otherwise /resume_session is unusable without reading the database.
    assert "session `" in message
    assert "/resume_session" in message
    # The relevant hit should come first.
    assert message.index("capital of france") < message.index("sourdough")


async def test_search_is_scoped_per_user(wire, monkeypatch):
    """A single session's history must not be searchable by another user."""
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    await run_async.complete_session_chat(
        **CTX, user_input="my private note", is_group=False, is_new_session=True
    )

    other = {**CTX, "user_discord_id": "user-2", "user_name": "someone-else"}
    result = await run_async.search_messages_and_list_sessions(
        **other, user_input="my private note", is_group=False
    )
    assert result["message"] == "No search results found.", result


async def test_search_degrades_to_keyword_when_embedding_fails(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    await run_async.complete_session_chat(
        **CTX, user_input="pgvector replaces meilisearch", is_group=False, is_new_session=True
    )

    async def no_embedding(text):
        return None
    monkeypatch.setattr(search_service, "embed", no_embedding)

    async with wire() as db:
        index_key = (await db.execute(select(SearchDocument))).scalars().first().index_key
        results = await search_service.hybrid_search(db, index_key, "pgvector")
    assert results and results[0]["score"] > 0, "keyword-only search should still match"


async def test_search_returns_nothing_for_an_unrelated_query(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    await run_async.complete_session_chat(
        **CTX, user_input="sourdough", is_group=False, is_new_session=True
    )
    async with wire() as db:
        index_key = (await db.execute(select(SearchDocument))).scalars().first().index_key
        # keyword-only, so an unrelated query scores zero and is filtered out
        results = await search_service.hybrid_search(db, index_key, "zzz", semantic_ratio=0.0)
    assert results == []


async def test_temperature_is_omitted_unless_configured(monkeypatch):
    """Reasoning models reject any temperature but their own default.

    gpt-5.6-luna returns 400 'temperature does not support 0.5 with this model',
    so sending it unconditionally broke every call against the default model.
    """
    from src.llm import chat as chat_module

    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop here")

    class FakeClient:
        chat = type("C", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(chat_module, "get_async_client", lambda p: FakeClient())

    with pytest.raises(RuntimeError):
        await chat_module.achat("hi", temperature=None)
    assert "temperature" not in captured, captured.keys()

    captured.clear()
    with pytest.raises(RuntimeError):
        await chat_module.achat("hi", temperature=0.5)
    assert captured["temperature"] == 0.5


async def test_a_rejected_temperature_is_retried_without_it(monkeypatch):
    from openai import BadRequestError

    from src.llm import chat as chat_module

    calls = []

    class FakeResponse:
        model = "gpt-5.6-luna"
        usage = type("U", (), {"prompt_tokens": 3, "completion_tokens": 2})()
        choices = [type("C", (), {"message": type("M", (), {"content": "ok", "reasoning_details": None})()})()]

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs.copy())
            if "temperature" in kwargs:
                raise BadRequestError(
                    "Unsupported value: 'temperature' does not support 0.5 with this model.",
                    response=type("R", (), {"status_code": 400, "headers": {}, "request": None})(),
                    body=None,
                )
            return FakeResponse()

    class FakeClient:
        chat = type("C", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(chat_module, "get_async_client", lambda p: FakeClient())

    result = await chat_module.achat("hi", temperature=0.5)
    assert result.text == "ok"
    assert len(calls) == 2, "should retry exactly once"
    assert "temperature" in calls[0] and "temperature" not in calls[1]


async def test_short_replies_are_not_marked_truncated(wire, monkeypatch):
    """Search used to append "...to be continued." to every reply, including
    ones well under the limit."""
    monkeypatch.setattr(run_async, "achat", await stub_chat(text="Paris."))
    await run_async.complete_session_chat(
        **CTX, user_input="capital of france", is_group=False, is_new_session=True
    )
    message = (
        await run_async.search_messages_and_list_sessions(
            **CTX, user_input="capital of france", is_group=False
        )
    )["message"]
    assert "Paris." in message
    assert "to be continued" not in message
    assert "…" not in message


async def test_long_replies_are_truncated_with_an_ellipsis(wire, monkeypatch):
    monkeypatch.setattr(run_async, "achat", await stub_chat(text="x" * 400))
    await run_async.complete_session_chat(
        **CTX, user_input="tell me a long story", is_group=False, is_new_session=True
    )
    message = (
        await run_async.search_messages_and_list_sessions(
            **CTX, user_input="tell me a long story", is_group=False
        )
    )["message"]
    assert "…" in message
    assert "x" * 260 not in message


async def test_group_search_points_at_the_group_resume_command(wire, monkeypatch):
    """The footer used to name /resume_session even for group results, which do
    not belong to that command."""
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    await run_async.complete_session_chat(
        **CTX, user_input="team standup notes", is_group=True, is_new_session=True
    )
    group = await run_async.search_messages_and_list_sessions(
        **CTX, user_input="team standup notes", is_group=True
    )
    assert "/resume_group_session" in group["message"], group["message"]

    await run_async.complete_session_chat(
        **CTX, user_input="team standup notes", is_group=False, is_new_session=True
    )
    single = await run_async.search_messages_and_list_sessions(
        **CTX, user_input="team standup notes", is_group=False
    )
    assert "/resume_session session_id" in single["message"]
    assert "/resume_group_session" not in single["message"]


async def test_truncated_results_say_how_many_matched(wire, monkeypatch):
    """A silent top-N cut made a correctly-ranked result look like it was never
    indexed at all."""
    monkeypatch.setattr(run_async, "achat", await stub_chat())
    for text in ("alpha topic one", "alpha topic two", "alpha topic three",
                 "alpha topic four", "alpha topic five", "alpha topic six"):
        await run_async.complete_session_chat(
            **CTX, user_input=text, is_group=False, is_new_session=False
        )

    message = (
        await run_async.search_messages_and_list_sessions(
            **CTX, user_input="alpha topic", is_group=False
        )
    )["message"]
    # Six match, fewer are shown, and the header must admit it.
    assert " of " in message, message.split("\n")[0]
    assert message.startswith("**"), message[:40]

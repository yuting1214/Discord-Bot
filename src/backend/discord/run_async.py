"""Command orchestration for the Discord bot.

Each command runs as short database transactions around the slow work, rather
than one long-lived unit: an LLM completion takes seconds, and holding a pooled
connection open across it is what exhausts the pool under concurrency. Embedding
calls are treated the same way.
"""

import logging

from src.backend.discord import service
from src.backend.discord.errors import describe
from src.backend.discord.utils import extract_uuid
from src.backend.fastapi.dependencies.database import AsyncSessionLocal
from src.backend.search.embeddings import embed
from src.backend.search.service import (
    DEFAULT_TOP_N,
    hybrid_search,
    index_document,
    to_conversation_ids_and_scores,
)
from src.llm.chat import achat
from src.llm.memory.memory_management import format_memory

logger = logging.getLogger(__name__)


def _render_search_results(results: list[dict], is_group: bool, shown: int) -> str:
    """Render hits as readable Discord text.

    Previously this was a raw json.dumps, which meant picking a session_id out of
    a wall of braces before /resume_session could be used at all.
    """
    total = len(results)
    results = results[:shown]
    header = f"**{len(results)} of {total} result(s)**" if total > len(results) else f"**{total} result(s)**"
    lines = [header]
    for i, hit in enumerate(results, 1):
        score = hit.get("query_score")
        lines.append(
            f"\n**{i}.** {hit['user_input']}"
            f"\n> {hit['llm_response']}"
            f"\n> score `{score}` · session `{hit['session_id']}`"
        )
    command = "resume_group_session" if is_group else "resume_session"
    lines.append(f"\nResume one with `/{command} session_id:<id>`")
    return "\n".join(lines)


def _format_messages_to_search_results(messages: list[dict], scores: list[float]) -> list[dict]:
    """Pair each user message with the model reply that followed it."""
    search_results = []
    pair: dict = {}
    score_index = 0
    for message in messages:
        if message["message_type"] == "user":
            pair = {
                "session_id": message["session_id"],
                "query_score": scores[score_index] if score_index < len(scores) else None,
                "user_input": message["content"],
            }
        elif pair:
            reply = message["content"]
            # Only mark it truncated when it actually was.
            pair["llm_response"] = reply if len(reply) <= 250 else reply[:250] + "…"
            search_results.append(pair)
            pair = {}
            score_index += 1
    return search_results


async def complete_session_chat(
    server_discord_id: str,
    server_name: str,
    owner_discord_id: str,
    channel_discord_id: str,
    channel_name: str,
    user_discord_id: str,
    user_name: str,
    user_input: str,
    is_group: bool,
    is_new_session: bool,
) -> dict:
    try:
        # Transaction 1: record the user's turn and gather the memory window.
        async with AsyncSessionLocal() as db:
            async with db.begin():
                user = await service.get_or_create_user(db, user_discord_id, user_name)
                server = await service.get_or_create_server(
                    db, server_discord_id, server_name, owner_discord_id, user
                )
                channel = await service.get_or_create_channel(
                    db, server.id, channel_discord_id, channel_name, user, is_group
                )
                session = await service.manage_session(
                    db, channel_discord_id, user, is_group, is_new_session
                )
                conversation = await service.create_conversation(db, session.id)
                await service.create_message(
                    db,
                    channel_discord_id=channel_discord_id,
                    session_id=session.id,
                    conversation_id=conversation.id,
                    user_id=user.id,
                    message_type="user",
                    content=user_input,
                )
                await service.create_command_log(
                    db, user.id, session.id, is_group, is_new_session
                )

                memory = (
                    []
                    if is_new_session
                    else format_memory(await service.get_latest_messages(db, session.id))
                )
                index_key = service.search_index_key(user.id, channel.id, is_group)
                session_id, conversation_id, user_id = session.id, conversation.id, user.id

        # Both network calls run with no database connection held.
        embedding = await embed(user_input)
        result = await achat(user_input, memory)

        # Transaction 2: record the model's turn and make the exchange searchable.
        async with AsyncSessionLocal() as db:
            async with db.begin():
                await service.create_message(
                    db,
                    channel_discord_id=channel_discord_id,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    message_type="model",
                    content=result.text,
                    reasoning_details=result.reasoning_details,
                )
                await service.end_conversation(db, conversation_id)
                await service.record_llm_usage(
                    db, session_id, result.model, result.input_tokens, result.output_tokens
                )
                await index_document(
                    db,
                    index_key=index_key,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    content=user_input,
                    embedding=embedding,
                )

        return {"llm_response": result.text}

    except Exception as e:
        logger.exception("complete_session_chat failed")
        return {"error": str(e), "hint": describe(e)}


async def resume_session(
    server_discord_id: str,
    server_name: str,
    owner_discord_id: str,
    channel_discord_id: str,
    channel_name: str,
    user_discord_id: str,
    user_name: str,
    user_input: str,
    is_group: bool,
) -> dict:
    resume_session_id = extract_uuid(user_input)
    if not resume_session_id:
        return {
            "message": (
                "That does not look like a session ID. Run `/search` (or "
                "`/search_group`) and copy the `session_id` from a result."
            )
        }

    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                user = await service.get_or_create_user(db, user_discord_id, user_name)
                server = await service.get_or_create_server(
                    db, server_discord_id, server_name, owner_discord_id, user
                )
                await service.get_or_create_channel(
                    db, server.id, channel_discord_id, channel_name, user, is_group
                )

                target = await service.get_session_if_exists(db, resume_session_id)
                if target is None:
                    return {
                        "message": (
                            f"No session found with ID `{resume_session_id}`. "
                            "Run `/search` to list sessions you can resume."
                        )
                    }

                for active in await service.find_active_sessions(
                    db, channel_discord_id, user.id, is_group
                ):
                    if active.id != target.id:
                        service.deactivate_session(active)
                service.activate_session(target)

        return {"message": f"Session - {resume_session_id} has resumed."}

    except Exception as e:
        logger.exception("resume_session failed")
        return {"error": str(e), "hint": describe(e), "message": describe(e)}


async def search_messages_and_list_sessions(
    server_discord_id: str,
    server_name: str,
    owner_discord_id: str,
    channel_discord_id: str,
    channel_name: str,
    user_discord_id: str,
    user_name: str,
    user_input: str,
    is_group: bool,
) -> dict:
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                user = await service.get_or_create_user(db, user_discord_id, user_name)
                server = await service.get_or_create_server(
                    db, server_discord_id, server_name, owner_discord_id, user
                )
                channel = await service.get_or_create_channel(
                    db, server.id, channel_discord_id, channel_name, user, is_group
                )
                index_key = service.search_index_key(user.id, channel.id, is_group)

        async with AsyncSessionLocal() as db:
            results = await hybrid_search(db, index_key, user_input)
            conversation_ids, scores = to_conversation_ids_and_scores(results)
            if not conversation_ids:
                return {"message": "No search results found."}
            raw_messages = await service.get_messages_by_conversations(db, conversation_ids)

        results = _format_messages_to_search_results(raw_messages, scores)
        if not results:
            return {"message": "No search results found."}
        return {"message": _render_search_results(results, is_group, DEFAULT_TOP_N)}

    except Exception as e:
        logger.exception("search_messages_and_list_sessions failed")
        return {"error": str(e), "hint": describe(e), "message": describe(e)}

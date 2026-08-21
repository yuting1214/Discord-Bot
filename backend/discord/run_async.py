"""Command orchestration for the Discord bot.

Each command runs as short database transactions around the slow work, rather
than one long-lived unit: an LLM completion takes seconds, and holding a pooled
connection open across it is what exhausts the pool under concurrency.
"""

import json
import logging

from backend.discord import service
from backend.discord.utils import extract_uuid, generate_uuid_key
from backend.fastapi.dependencies.database import AsyncSessionLocal
from backend.meilisearch.format import (
    format_documents_to_search_results,
    format_search_results_to_conversation_ids_and_scores,
)
from backend.meilisearch.insert import insert_documents_async
from backend.meilisearch.search import hybrid_search_async
from llm.chat import achat
from llm.memory.memory_management import format_memory

logger = logging.getLogger(__name__)


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
            pair["llm_response"] = message["content"][:250] + "...to be continued."
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
                index_key = (
                    str(channel.id) if is_group else generate_uuid_key(user.id, channel.id)
                )
                session_id, conversation_id, user_id = session.id, conversation.id, user.id

        # Index outside the transaction: a search-index failure must not roll
        # back the user's message.
        try:
            await insert_documents_async(
                index_key,
                [{
                    "conversation_id": str(conversation_id),
                    "user_input": user_input,
                    "session_id": str(session_id),
                }],
            )
        except Exception:
            logger.exception("Failed to index message for search; continuing")

        # No database connection is held across the completion.
        result = await achat(user_input, memory)

        # Transaction 2: record the model's turn.
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

        return {"llm_response": result.text}

    except Exception as e:
        logger.exception("complete_session_chat failed")
        return {"error": str(e)}


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
        return {"message": "Invalid UUID input."}

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
                    return {"message": f"Session - {resume_session_id} does not exist!"}

                for active in await service.find_active_sessions(
                    db, channel_discord_id, user.id, is_group
                ):
                    if active.id != target.id:
                        service.deactivate_session(active)
                service.activate_session(target)

        return {"message": f"Session - {resume_session_id} has resumed."}

    except Exception as e:
        logger.exception("resume_session failed")
        return {"error": str(e), "message": str(e)}


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
                index_key = str(channel.id) if is_group else generate_uuid_key(user.id, channel.id)

        documents = await hybrid_search_async(index_key, user_input)
        conversation_results = format_documents_to_search_results(documents)
        conversation_ids, scores = format_search_results_to_conversation_ids_and_scores(
            conversation_results
        )

        if not conversation_ids:
            return {"message": "No search results found."}

        async with AsyncSessionLocal() as db:
            raw_messages = await service.get_messages_by_conversations(db, conversation_ids)

        results = _format_messages_to_search_results(raw_messages, scores)
        return {"message": json.dumps(results, indent=4)}

    except Exception as e:
        logger.exception("search_messages_and_list_sessions failed")
        return {"error": str(e), "message": str(e)}

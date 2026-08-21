from typing import List, Dict
from backend.fastapi.request_handler.api_requests import get_request, post_request
from backend.fastapi.request_handler.api_requests_async import get_request_async, post_request_async

def create_message(channel_discord_id: str, session_id: str, conversation_id: str, user_id: str, message_type: str, user_input: str, resources_to_rollback: list) -> dict:
    message_data = {
        "channel_discord_id": channel_discord_id,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "content": user_input,
        "message_type": message_type,
        "user_id": user_id,
    }
    new_message = post_request("messages/", message_data)
    resources_to_rollback.append(("create", "messages", {"resource_id": new_message["id"]}))

    return new_message

async def create_message_async(channel_discord_id: str, session_id: str, conversation_id: str, user_id: str, message_type: str, user_input: str, resources_to_rollback: list) -> dict:
    message_data = {
        "channel_discord_id": channel_discord_id,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "content": user_input,
        "message_type": message_type,
        "user_id": user_id,
    }
    new_message = await post_request_async("messages/", message_data)
    resources_to_rollback.append(("create", "messages", {"resource_id": new_message["id"]}))
    return new_message

def get_messages_by_conversations(conversation_ids: list) -> list:
    query = {
        "conversation_ids": conversation_ids
    }
    return get_request("messages/conversations/", query)

async def get_messages_by_conversations_async(conversation_ids: List[str]) -> list:
    query = {
        "conversation_ids": conversation_ids
    }
    return await get_request_async("messages/conversations/", query)

def format_messages_to_search_results(messages: List[Dict[str, str]], scores: List[float]) -> list:
    search_results = []
    message_dict_pair = {}
    scores_index = 0
    for message in messages:
        if message["message_type"] == "user":
            message_dict_pair["session_id"] = message["session_id"]
            message_dict_pair["query_score"] = scores[scores_index]
            message_dict_pair["user_input"] = message["content"]
        else:
            message_dict_pair["llm_response"] = message["content"][:250] + '...to be continued.' # truncate response
            search_results.append(message_dict_pair)
            message_dict_pair = {}
            scores_index += 1

    return search_results
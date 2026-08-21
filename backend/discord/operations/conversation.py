from datetime import datetime

from backend.constants import CURRENT_TIMEZONE
from backend.fastapi.request_handler.api_requests import get_request, post_request, put_request
from backend.fastapi.request_handler.api_requests_async import get_request_async, post_request_async, put_request_async


def create_conversation(session_id: str, resources_to_rollback: list) -> dict:
    conversation_data = {"session_id": session_id}
    new_conversation = post_request("conversations/", conversation_data)
    resources_to_rollback.append(("create", "conversations", {"resource_id": new_conversation["id"]}))
    return new_conversation

async def create_conversation_async(session_id: str, resources_to_rollback: list) -> dict:
    conversation_data = {"session_id": session_id}
    new_conversation = await post_request_async("conversations/", conversation_data)
    resources_to_rollback.append(("create", "conversations", {"resource_id": new_conversation["id"]}))
    return new_conversation

def update_conversation(conversation_id: str, resources_to_rollback: list) -> None:
    # Fetch the current state before updating
    current_conversation = get_request(f"conversations/{conversation_id}")

    conversation_update_data = {
        "end_time":  datetime.now(CURRENT_TIMEZONE).isoformat(),
    }
    put_request(f"conversations/{conversation_id}", conversation_update_data)

    # Add the rollback operation for updated resource
    resources_to_rollback.append(("update", "conversations", {
        "resource_id": conversation_id,
        "previous_state": current_conversation,
    }))

async def update_conversation_async(conversation_id: str, resources_to_rollback: list) -> None:
    # Fetch the current state before updating
    current_conversation = await get_request_async(f"conversations/{conversation_id}")

    conversation_update_data = {
        "end_time": datetime.now(CURRENT_TIMEZONE).isoformat(),
    }
    await put_request_async(f"conversations/{conversation_id}", conversation_update_data)

    # Add the rollback operation for updated resource
    resources_to_rollback.append(("update", "conversations", {
        "resource_id": conversation_id,
        "previous_state": current_conversation,
    }))
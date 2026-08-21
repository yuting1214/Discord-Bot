from typing import Any

Message = dict[str, Any]


def format_memory(history: list[dict[str, Any]]) -> list[Message]:
    """
    Format database message rows into chat-completion messages.

    Rows arrive newest-first from the query and are reversed into chronological
    order, which is what the model expects.

    Assistant rows carry their stored ``reasoning_details`` back unmodified so a
    reasoning model continues its chain instead of restarting it.

    Args:
        history (List[Dict[str, Any]]): The history of messages from database query.

    Returns:
        List[Message]: The formatted messages as a memory.
    """
    messages: list[Message] = []
    for row in history[::-1]:
        is_user = row["message_type"] == "user"
        message: Message = {
            "role": "user" if is_user else "assistant",
            "content": row["content"],
        }
        if not is_user and row.get("reasoning_details"):
            message["reasoning_details"] = row["reasoning_details"]
        messages.append(message)
    return messages

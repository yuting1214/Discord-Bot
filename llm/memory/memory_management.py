from typing import Dict, List

Message = Dict[str, str]


def format_memory(history: List[Dict[str, str]]) -> List[Message]:
    """
    Format database message rows into chat-completion messages.

    Rows arrive newest-first from the query and are reversed into chronological
    order, which is what the model expects.

    Args:
        history (List[Dict[str, str]]): The history of messages from database query.

    Returns:
        List[Message]: The formatted messages as a memory.
    """
    return [
        {
            "role": "user" if message["message_type"] == "user" else "assistant",
            "content": message["content"],
        }
        for message in history[::-1]
    ]

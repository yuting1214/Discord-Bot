from typing import List

from backend.constants import MEMORY_WINDOW_SIZE
from backend.fastapi.request_handler.api_requests import get_request
from backend.fastapi.request_handler.api_requests_async import get_request_async
from llm.chat import Message, achat, chat
from llm.memory.memory_management import format_memory


def llm_api_call(user_input: str, memory: list) -> str:
    try:
        return chat(user_input, memory).text
    except Exception as e:
        raise RuntimeError(f"Failed to process LLM response: {str(e)}") from e


async def llm_api_call_async(user_input: str, memory: list) -> str:
    try:
        result = await achat(user_input, memory)
        return result.text
    except Exception as e:
        raise RuntimeError(f"Failed to process LLM response: {str(e)}") from e


def prepare_memory_for_llm(session_id: str, window_size: int = MEMORY_WINDOW_SIZE) -> List[Message]:
    latest_messages = get_request("messages/latest/", params={"session_id": session_id, "n": window_size})
    return format_memory(latest_messages)


async def prepare_memory_for_llm_async(
    session_id: str,
    window_size: int = MEMORY_WINDOW_SIZE
) -> List[Message]:
    # Fetch latest messages asynchronously
    latest_messages = await get_request_async("messages/latest/", params={"session_id": session_id, "n": window_size})

    # Format memory
    return format_memory(latest_messages)

from typing import List, Tuple
from backend.fastapi.request_handler.api_requests import get_request
from backend.fastapi.request_handler.api_requests_async import get_request_async
from backend.constants import MEMORY_WINDOW_SIZE
from llm.llm_text_chain import llm_OpenRouter_memory_chain, llm_OpenAI_memory_chain, llm_OpenAI_memory_chain_async
from llm.memory.memory_management import format_memory

def llm_api_call(user_input: str, memory: list) -> str:
    try:
        llm_response = llm_OpenAI_memory_chain(user_input, memory)
        return llm_response
    except Exception as e:
        raise RuntimeError(f"Failed to process LLM response: {str(e)}")
    
async def llm_api_call_async(user_input: str, memory: list) -> str:
    try:
        llm_response = await llm_OpenAI_memory_chain_async(user_input, memory)
        return llm_response
    except Exception as e:
        raise RuntimeError(f"Failed to process LLM response: {str(e)}")


def prepare_memory_for_llm(session_id: str, window_size: int = MEMORY_WINDOW_SIZE) -> List[Tuple[str, str]]:
    latest_messages = get_request("messages/latest/", params={"session_id": session_id, "n": window_size})
    return format_memory(latest_messages)

async def prepare_memory_for_llm_async(
    session_id: str, 
    window_size: int = MEMORY_WINDOW_SIZE
) -> List[Tuple[str, str]]:
    # Fetch latest messages asynchronously
    latest_messages = await get_request_async("messages/latest/", params={"session_id": session_id, "n": window_size})
    
    # Format memory
    return format_memory(latest_messages)

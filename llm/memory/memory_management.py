from typing import List, Tuple, Dict

def format_memory(history: List[Dict[str, str]]) -> List[Tuple[str, str]]:
    """
    Format the memory format in chatbot.
    
    Args:
        history (List[Dict[str, str]]): The history of messages from database query.
    
    Returns:
        List[Tuple[str, str]]: The formatted messages as a memory.
    """
    return [('human' if message["message_type"] == 'user' else 'ai', message["content"]) for message in history[::-1]]
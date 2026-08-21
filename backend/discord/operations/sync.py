from backend.discord.operations.user import get_or_create_user
from backend.discord.operations.server import get_or_create_server
from backend.discord.operations.channel import get_or_create_channel
from backend.discord.operations.session import (
    manage_session,
    get_session_if_exists,
    find_active_sessions,
    activate_session,
    deactivate_session
)
from backend.discord.operations.conversation import create_conversation, update_conversation
from backend.discord.operations.message import (
    create_message,
    get_messages_by_conversations,
    format_messages_to_search_results
)
from backend.discord.operations.command_log import create_command_log
from backend.discord.operations.llm import llm_api_call, prepare_memory_for_llm
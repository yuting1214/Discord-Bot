from backend.fastapi.request_handler.api_requests import post_request, get_request
from backend.fastapi.request_handler.api_requests_async import post_request_async, get_request_async

def create_command_log(user_id: str, session_id: str, is_group: bool, is_new_session: bool, resources_to_rollback: list) -> dict:
    command_name = (
        "start_group_session" if is_group and is_new_session else
        "bot_group" if is_group else
        "start_session" if is_new_session else
        "bot"
    )
    command = get_request(f"commands/name/{command_name}")
    command_log_data = {
        "user_id": user_id,
        "session_id": session_id,
        "command_id": command["id"]
    }
    new_command_log = post_request("command_logs/", command_log_data)
    resources_to_rollback.append(("create", "command_logs", {"resource_id": new_command_log["id"]}))
    return new_command_log

async def create_command_log_async(
    user_id: str,
    session_id: str,
    is_group: bool,
    is_new_session: bool,
    resources_to_rollback: list
) -> dict:
    command_name = (
        "start_group_session" if is_group and is_new_session else
        "bot_group" if is_group else
        "start_session" if is_new_session else
        "bot"
    )
    # Fetch command asynchronously
    command = await get_request_async(f"commands/name/{command_name}")
    
    command_log_data = {
        "user_id": user_id,
        "session_id": session_id,
        "command_id": command["id"]
    }
    
    # Create command log asynchronously
    new_command_log = await post_request_async("command_logs/", command_log_data)
    
    # Append the new command log to resources to rollback
    resources_to_rollback.append(("create", "command_logs", {"resource_id": new_command_log["id"]}))
    
    return new_command_log

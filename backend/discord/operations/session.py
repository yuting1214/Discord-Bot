from datetime import datetime

import httpx
import requests

from backend.constants import CURRENT_TIMEZONE
from backend.fastapi.request_handler.api_requests import get_request, post_request, put_request
from backend.fastapi.request_handler.api_requests_async import get_request_async, post_request_async, put_request_async


def manage_session(channel_discord_id: str, user_id: str, is_group: bool, is_new_session: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> dict:
    if is_new_session:
        terminate_active_sessions(channel_discord_id, user_id, is_group, resources_to_rollback)
        current_session = create_session(channel_discord_id, user_id, is_group, resources_to_rollback)
    else:
        current_session = get_or_create_current_session(channel_discord_id, user_id, is_group, resources_to_rollback)
    
    return current_session

async def manage_session_async(channel_discord_id: str, user_id: str, is_group: bool, is_new_session: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> dict:
    if is_new_session:
        await terminate_active_sessions_async(channel_discord_id, user_id, is_group, resources_to_rollback)
        current_session = await create_session_async(channel_discord_id, user_id, is_group, resources_to_rollback)
    else:
        current_session = await get_or_create_current_session_async(channel_discord_id, user_id, is_group, resources_to_rollback)
    
    return current_session

def get_session_if_exists(session_id: str) -> dict | None:
    try:
        return get_request(f"sessions/{session_id}")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None
        else:
            raise e
        
async def get_session_if_exists_async(session_id: str) -> dict | None:
    async with httpx.AsyncClient() as client:
        try:
            return await get_request_async(f"sessions/{session_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            else:
                raise e
        
def create_session(channel_discord_id: str, user_id: str, is_group: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> dict:
    session_data = {
        "channel_discord_id": channel_discord_id,
        "is_active": True,
        "is_group": is_group,
        "users": [user_id]
    }
    new_session = post_request("sessions/", session_data)
    resources_to_rollback.append(("create", "sessions", {"resource_id": new_session["id"]}))
    return new_session

async def create_session_async(channel_discord_id: str, user_id: str, is_group: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> dict:
    session_data = {
        "channel_discord_id": channel_discord_id,
        "is_active": True,
        "is_group": is_group,
        "users": [user_id]
    }
    new_session = await post_request_async("sessions/", session_data)
    resources_to_rollback.append(("create", "sessions", {"resource_id": new_session["id"]}))
    return new_session

def get_or_create_current_session(channel_discord_id: str, user_id: str, is_group: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> dict:
    session_data = {"channel_discord_id": channel_discord_id} if is_group else {"user_id": user_id}
    endpoint = f"sessions/current/{'group' if is_group else 'single'}/"
    
    try:
        current_session = get_request(endpoint, session_data)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            current_session = create_session(channel_discord_id, user_id, is_group, resources_to_rollback)
        else:
            raise e
    
    return current_session

async def get_or_create_current_session_async(channel_discord_id: str, user_id: str, is_group: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> dict:
    session_data = {"channel_discord_id": channel_discord_id} if is_group else {"user_id": user_id}
    endpoint = f"sessions/current/{'group' if is_group else 'single'}/"
    
    try:
        current_session = await get_request_async(endpoint, session_data)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            current_session = await create_session_async(channel_discord_id, user_id, is_group, resources_to_rollback)
        else:
            raise e
    
    return current_session

def terminate_active_sessions(channel_discord_id: str, user_id: str, is_group: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> None:
    try:
        active_sessions = find_active_sessions(channel_discord_id, user_id, is_group)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return
        else:
            raise e
    else:
        for session in active_sessions:
            deactivate_session(session["id"], session, resources_to_rollback)

async def terminate_active_sessions_async(channel_discord_id: str, user_id: str, is_group: bool, resources_to_rollback: list[tuple[str, str, dict]]) -> None:
    try:
        active_sessions = await find_active_sessions_async(channel_discord_id, user_id, is_group)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return
        else:
            raise e
    else:
        for session in active_sessions:
            await deactivate_session_async(session["id"], session, resources_to_rollback)

def find_active_sessions(channel_discord_id: str, user_id: str, is_group: bool) -> list[dict] | None:
    session_data = {"channel_discord_id": channel_discord_id} if is_group else {"user_id": user_id}
    endpoint = f"sessions/active/{'group' if is_group else 'single'}/"
    active_sessions = get_request(endpoint, session_data)
    return active_sessions

async def find_active_sessions_async(channel_discord_id: str, user_id: str, is_group: bool) -> list[dict] | None:
    session_data = {"channel_discord_id": channel_discord_id} if is_group else {"user_id": user_id}
    endpoint = f"sessions/active/{'group' if is_group else 'single'}/"
    active_sessions = await get_request_async(endpoint, session_data)
    return active_sessions

def activate_session(session_id: str,  target_session: dict, resources_to_rollback: list) -> None:
    session_update_data = {
        "is_active": True,
        "end_time": None
    }
    put_request(f"sessions/{session_id}", session_update_data)
    resources_to_rollback.append((
        "update",
        "sessions",
        {"resource_id": session_id, "previous_state": target_session}
    ))

async def activate_session_async(session_id: str, target_session: dict, resources_to_rollback: list[tuple[str, str, dict]]) -> None:
    session_update_data = {
        "is_active": True,
        "end_time": None
    }
    await put_request_async(f"sessions/{session_id}", session_update_data)
    resources_to_rollback.append((
        "update",
        "sessions",
        {"resource_id": session_id, "previous_state": target_session}
    ))

def deactivate_session(session_id: str, target_session: dict, resources_to_rollback: list) -> None:
    session_update_data = {
        "is_active": False,
        "end_time": datetime.now(CURRENT_TIMEZONE).isoformat()
    }
    put_request(f"sessions/{session_id}", session_update_data)
    resources_to_rollback.append((
        "update",
        "sessions",
        {"resource_id": session_id, "previous_state": target_session}
    ))

async def deactivate_session_async(session_id: str, target_session: dict, resources_to_rollback: list[tuple[str, str, dict]]) -> None:
    session_update_data = {
        "is_active": False,
        "end_time": datetime.now(CURRENT_TIMEZONE).isoformat()
    }
    await put_request_async(f"sessions/{session_id}", session_update_data)
    resources_to_rollback.append((
        "update",
        "sessions",
        {"resource_id": session_id, "previous_state": target_session}
    ))
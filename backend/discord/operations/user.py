import httpx
import requests
from backend.fastapi.request_handler.api_requests import post_request, get_request
from backend.fastapi.request_handler.api_requests_async import post_request_async, get_request_async
from backend.meilisearch.insert import initiate_index

def get_or_create_user(user_discord_id: str, user_name: str, resources_to_rollback: list) -> str:
    user_data = {"discord_id": user_discord_id}
    try:
        user = get_request("user/", user_data)
        return user["id"]
    except requests.exceptions.HTTPError as e:
        # User not existed
        if e.response.status_code == 404:
            user_data = {"discord_id": user_discord_id, "username": user_name}
            new_user = post_request("users/", user_data)
            resources_to_rollback.append(("create", "users", {"resource_id": new_user["id"]}))
            return new_user["id"]
        else:
            raise e
        
async def get_or_create_user_async(user_discord_id: str, user_name: str, resources_to_rollback: list) -> str:
    user_data = {"discord_id": user_discord_id}
    try:
        user = await get_request_async("user/", user_data)
        return user["id"]
    except httpx.HTTPStatusError as e:
        # User not existed
        if e.response.status_code == 404:
            user_data = {"discord_id": user_discord_id, "username": user_name}
            new_user = await post_request_async("users/", user_data)
            resources_to_rollback.append(("create", "users", {"resource_id": new_user["id"]}))
            return new_user["id"]
        else:
            raise e
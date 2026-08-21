import requests
from backend.fastapi.request_handler.api_requests import post_request, get_request
from backend.meilisearch.insert import initiate_index
from backend.discord.utils import generate_uuid_key

# def get_or_create_channel(server_id: str, channel_discord_id: str, channel_name: str, user_id: str, is_group: bool, resources_to_rollback: list) -> str:
#     try:
#         channel = get_request("channel/", {"channel_discord_id": channel_discord_id})
#         return channel["id"]
#     except requests.exceptions.HTTPError as e:
#         # Channel not existed
#         if e.response.status_code == 404:
#             channel_data = {
#                 "server_id": server_id,
#                 "channel_discord_id": channel_discord_id,
#                 "channel_name": channel_name,
#                 "users": [user_id]
#             }
#             new_channel = post_request("channels/", channel_data)
#             resources_to_rollback.append(("create", "channels", {"resource_id": new_channel["id"]}))
#             # Create a new index for the user(Meilisearch)
#             if not is_group:
#                 uuid_key = generate_uuid_key(user_id, new_channel["id"])
#                 new_index = initiate_index(uuid_key)
#             return new_channel["id"]
#         else:
#             raise e
        
def get_or_create_channel(server_id: str, channel_discord_id: str, channel_name: str, user_id: str, is_group: bool, resources_to_rollback: list) -> str:
    try:
        # Query parameters for the GET request
        params = {
            "channel_discord_id": channel_discord_id,
            "is_group": is_group
        }
        if not is_group:
            params["user_id"] = user_id

        channel = get_request("channel/", params)
        return channel["id"]
    except requests.exceptions.HTTPError as e:
        # Channel not existed
        if e.response.status_code == 404:
            channel_data = {
                "server_id": server_id,
                "channel_discord_id": channel_discord_id,
                "channel_name": channel_name,
                "is_group": is_group,
            }
            if is_group:
                channel_data["users"] = [user_id]
            else:
                channel_data["user_id"] = user_id
                
            new_channel = post_request("channels/", channel_data)
            resources_to_rollback.append(("create", "channels", {"resource_id": new_channel["id"]}))
            
            # Create a new index for the user (Meilisearch)
            uuid_key = new_channel["id"] if is_group else generate_uuid_key(user_id, new_channel["id"])
            new_index = initiate_index(uuid_key)
            
            return new_channel["id"]
        else:
            raise e
import requests
from backend.fastapi.request_handler.api_requests import post_request, get_request
from backend.meilisearch.insert import initiate_index

def get_or_create_server(server_discord_id: str, server_name: str, owner_discord_id: str, user_id: str, resources_to_rollback: list) -> str:
    try:
        server = get_request("server/", {"server_discord_id": server_discord_id})
        return server["id"]
    except requests.exceptions.HTTPError as e:
        # server not existed
        if e.response.status_code == 404:
            server_data = {
                "server_discord_id": server_discord_id,
                "server_name": server_name,
                "owner_discord_id": owner_discord_id,
                "users": [user_id]
            }
            new_server = post_request("servers/", server_data)
            resources_to_rollback.append(("create", "servers", {"resource_id": new_server["id"]}))
            return new_server["id"]
        else:
            raise e
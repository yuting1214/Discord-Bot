import os

import httpx
import requests


def enable_experimental_features() -> dict | None:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/experimental-features/"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {'vectorStore': True}

    try:
        response = requests.patch(url, json=data, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None
    
def configure_embedder(index_uid: str) -> dict | None:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{index_uid}/settings"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {
        "embedders": {
            "openai": {
                "source":  "openAi",
                "apiKey": os.getenv("OPENAI_API_KEY"),
                "model": "text-embedding-3-small",
                "documentTemplate":  "An user query: '{{doc.user_input}}'",
                "dimensions": 1536 
            }
        }
    }

    try:
        response = requests.patch(url, json=data, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

async def configure_embedder_async(index_uid: str) -> dict | None:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{index_uid}/settings"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {
        "embedders": {
            "openai": {
                "source": "openAi",
                "apiKey": os.getenv("OPENAI_API_KEY"),
                "model": "text-embedding-3-small",
                "documentTemplate": "An user query: '{{doc.user_input}}'",
                "dimensions": 1536
            }
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"An error occurred: {e}")
            return None
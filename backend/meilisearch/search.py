import os
import httpx
import requests
from typing import Optional

def hybrid_search(index_uid: str, user_query: str, semanticRatio: float = 0.5, top_n: int = 3) -> Optional[dict]:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{index_uid}/search"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {
        "q": user_query,
        "showRankingScore": True,
        "limit": top_n,
        "hybrid": {
            "semanticRatio": semanticRatio,
            "embedder": "openai"
        }
    }

    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        return response.json()
    except requests.exceptions.RequestException as e:
        if response.status_code == 404:
            print(f"The index {index_uid} does not exist.")
        else:
            print(f"An error occurred: {e}")
        return None

async def hybrid_search_async(
    index_uid: str,
    user_query: str,
    semanticRatio: float = 0.5,
    top_n: int = 3
) -> Optional[dict]:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{index_uid}/search"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {
        "q": user_query,
        "showRankingScore": True,
        "limit": top_n,
        "hybrid": {
            "semanticRatio": semanticRatio,
            "embedder": "openai"
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses
            return response.json()
        except httpx.RequestError as e:
            if e.response and e.response.status_code == 404:
                print(f"The index {index_uid} does not exist.")
            else:
                print(f"An error occurred: {e}")
            return None
    
def fulltext_search(index_uid: str, user_query: str, top_n: int = 3) -> Optional[dict]:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{index_uid}/search"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {
        "q": user_query,
        "limit": top_n,
    }

    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        return response.json()
    except requests.exceptions.RequestException as e:
        if response.status_code == 404:
            print(f"The index {index_uid} does not exist.")
        else:
            print(f"An error occurred: {e}")
        return None
    
async def fulltext_search_async(
    index_uid: str,
    user_query: str,
    top_n: int = 3
) -> Optional[dict]:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{index_uid}/search"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    data = {
        "q": user_query,
        "limit": top_n,
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses
            return response.json()
        except httpx.RequestError as e:
            if e.response and e.response.status_code == 404:
                print(f"The index {index_uid} does not exist.")
            else:
                print(f"An error occurred: {e}")
            return None
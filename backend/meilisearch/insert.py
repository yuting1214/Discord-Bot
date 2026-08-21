import os

import httpx
import requests

from backend.fastapi.schemas.document import DocumentSchema
from backend.meilisearch.config import meilisearch_client
from backend.meilisearch.setup import configure_embedder, configure_embedder_async


def initiate_index(uid: str) -> dict:
    # Create the index
    index = create_index(uid)
    # Configure the embedder
    embedder = configure_embedder(uid)
    return index

async def initiate_index_async(uid: str) -> dict | None:
    index = await create_index_async(uid)
    embedder = await configure_embedder_async(uid)
    return index

def create_index(uid: str) -> dict:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    index_schema = {
        "uid": uid,
        "primaryKey": "conversation_id"
    }
    try:
        response = requests.post(url, json=index_schema, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

async def create_index_async(uid: str) -> dict | None:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    index_schema = {
        "uid": uid,
        "primaryKey": "conversation_id"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=index_schema, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"An error occurred: {e}")
            return None

def insert_documents(uid: str, documents: list[DocumentSchema]) -> dict[str, str]:
    with meilisearch_client() as client:
        try:
            # Get or create the index
            index = client.index(uid)
            # Add documents to the index
            response = index.add_documents(documents)
            return response
        except Exception as e:
            print(f"An error occurred: {e}")
            return None

async def insert_documents_async(uid: str, documents: list[dict[str, str]]) -> dict[str, str]:
    host = os.getenv("MEILI_HOST", "http://localhost:7700")
    url = f"{host}/indexes/{uid}/documents"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("MEILI_MASTER_KEY")}'
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.put(url, json=documents, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"An error occurred: {e}")
            return None
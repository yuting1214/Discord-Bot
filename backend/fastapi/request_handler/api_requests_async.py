
from typing import AsyncGenerator, List, Tuple, Dict, Any, Optional
import httpx
from urllib.parse import urljoin
from contextlib import asynccontextmanager
from backend.constants import API_BASE_URL_ASYNC
    
@asynccontextmanager
async def rollback_manager() -> AsyncGenerator[List[Tuple[str, str, dict]], None]:
    resources_to_rollback: List[Tuple[str, str, dict]] = []
    async with httpx.AsyncClient() as client:
        try:
            yield resources_to_rollback
        except Exception as e:
            for http_method, resource_type, resource_data in reversed(resources_to_rollback):
                if http_method == "update":
                    # Restore the previous state of the resource
                    await client.post(urljoin(API_BASE_URL_ASYNC, f"{resource_type}/{resource_data['resource_id']}"), json=resource_data['previous_state'])
                elif http_method == "create":
                    # Default behavior for created resources: delete the resource
                    await client.delete(urljoin(API_BASE_URL_ASYNC, f"{resource_type}/{resource_data['resource_id']}"))
                # Additional handling can be added here for different resource types or methods
            raise e

async def post_request_async(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.post(urljoin(API_BASE_URL_ASYNC, endpoint), json=data)
        response.raise_for_status()
        return response.json()

async def get_request_async(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(urljoin(API_BASE_URL_ASYNC, endpoint), params=params)
        response.raise_for_status()
        return response.json()

async def put_request_async(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.put(urljoin(API_BASE_URL_ASYNC, endpoint), json=data)
        response.raise_for_status()
        return response.json()
import requests
from contextlib import contextmanager
from urllib.parse import urljoin
from backend.constants import API_BASE_URL_SYNC
from typing import Any, Dict, List, Tuple, Optional, Generator

@contextmanager
def rollback_manager() -> Generator[List[Tuple[str, str, dict]], None, None]:
    resources_to_rollback: List[Tuple[str, str, dict]] = []
    try:
        yield resources_to_rollback
    except Exception as e:
        for http_method, resource_type, resource_data in reversed(resources_to_rollback):
            if http_method == "update":
                # Restore the previous state of the resource
                post_request(f"{resource_type}/{resource_data['resource_id']}", resource_data['previous_state'])
            elif http_method == "create":
                # Default behavior for created resources: delete the resource
                requests.delete(urljoin(API_BASE_URL_SYNC, f"{resource_type}/{resource_data['resource_id']}"))
            # Additional handling can be added here for different resource types or methods
        raise e

def post_request(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(urljoin(API_BASE_URL_SYNC, endpoint), json=data)
    response.raise_for_status()
    return response.json()

def get_request(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = requests.get(urljoin(API_BASE_URL_SYNC, endpoint), params=params)
    response.raise_for_status()
    return response.json()

def put_request(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.put(urljoin(API_BASE_URL_SYNC, endpoint), json=data)
    response.raise_for_status()
    return response.json()

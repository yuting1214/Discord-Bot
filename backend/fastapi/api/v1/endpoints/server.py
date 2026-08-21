from uuid import UUID

from fastapi import APIRouter, Depends

from backend.fastapi.crud import ServerService
from backend.fastapi.schemas import ServerBase, ServerCreate, ServerSchema

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/servers/", response_model=ServerSchema)
def create_server(server_data: ServerCreate, service: ServerService = Depends()):
    return service.create_server(server_data)

@router_sync.get("/servers/", response_model=list[ServerSchema])
def get_servers(skip: int = 0, limit: int = 30, service: ServerService = Depends()):
    return service.get_servers(skip, limit)

@router_sync.get("/server/", response_model=ServerSchema)
def get_server(server_discord_id: str, service: ServerService = Depends()):
    return service.get_server_by_server_discord_id(server_discord_id)

@router_sync.put("/servers/{server_id}", response_model=ServerSchema)
def update_server(server_id: UUID, server_data: ServerBase, service: ServerService = Depends()):
    return service.update_server(server_id, server_data)

@router_sync.delete("/servers/{server_id}", response_model=ServerSchema)
def delete_server(server_id: UUID, service: ServerService = Depends()):
    return service.delete_server(server_id)

# Asynchronous Endpoints
@router_async.post("/servers/", response_model=ServerSchema)
async def create_server_async(server_data: ServerCreate, service: ServerService = Depends()):
    return await service.create_server_async(server_data)

@router_async.delete("/servers/{server_id}", response_model=ServerSchema)
def delete_server_async(server_id: UUID, service: ServerService = Depends()):
    return service.delete_server_async(server_id)
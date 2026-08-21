from uuid import UUID

from fastapi import APIRouter, Depends

from backend.fastapi.crud import ServerService
from backend.fastapi.schemas import ServerBase, ServerCreate, ServerSchema

router = APIRouter()


@router.post("/servers/", response_model=ServerSchema)
async def create_server(server_data: ServerCreate, service: ServerService = Depends()):
    return await service.create(server_data)


@router.get("/servers/", response_model=list[ServerSchema])
async def list_servers(skip: int = 0, limit: int = 30, service: ServerService = Depends()):
    return await service.list(skip, limit)


@router.get("/servers/{server_id}", response_model=ServerSchema)
async def get_server(server_id: UUID, service: ServerService = Depends()):
    return await service.get(server_id)


@router.put("/servers/{server_id}", response_model=ServerSchema)
async def update_server(server_id: UUID, server_data: ServerBase, service: ServerService = Depends()):
    return await service.update(server_id, server_data)


@router.delete("/servers/{server_id}", response_model=ServerSchema)
async def delete_server(server_id: UUID, service: ServerService = Depends()):
    return await service.delete(server_id)


@router.get("/server/", response_model=ServerSchema | None)
async def get_server_by_discord_id(server_discord_id: str, service: ServerService = Depends()):
    return await service.get_by_server_discord_id(server_discord_id)

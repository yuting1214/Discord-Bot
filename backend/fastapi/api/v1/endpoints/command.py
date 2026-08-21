from uuid import UUID

from fastapi import APIRouter, Depends

from backend.fastapi.crud import CommandService
from backend.fastapi.schemas import CommandBase, CommandCreate, CommandSchema

router = APIRouter()


@router.post("/commands/", response_model=CommandSchema)
async def create_command(command_data: CommandCreate, service: CommandService = Depends()):
    return await service.create(command_data)


@router.get("/commands/", response_model=list[CommandSchema])
async def list_commands(skip: int = 0, limit: int = 30, service: CommandService = Depends()):
    return await service.list(skip, limit)


@router.get("/commands/{command_id}", response_model=CommandSchema)
async def get_command(command_id: UUID, service: CommandService = Depends()):
    return await service.get(command_id)


@router.put("/commands/{command_id}", response_model=CommandSchema)
async def update_command(command_id: UUID, command_data: CommandBase, service: CommandService = Depends()):
    return await service.update(command_id, command_data)


@router.delete("/commands/{command_id}", response_model=CommandSchema)
async def delete_command(command_id: UUID, service: CommandService = Depends()):
    return await service.delete(command_id)


@router.get("/commands/name/{name}", response_model=CommandSchema | None)
async def get_command_by_name(name: str, service: CommandService = Depends()):
    return await service.get_by_name(name)

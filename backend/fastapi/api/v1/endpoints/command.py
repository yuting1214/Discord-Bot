from uuid import UUID

from fastapi import APIRouter, Depends

from backend.fastapi.crud import CommandService
from backend.fastapi.schemas import CommandBase, CommandCreate, CommandSchema

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/commands/", response_model=CommandSchema)
def create_command(command_data: CommandCreate, service: CommandService = Depends()):
    return service.create_command(command_data)

@router_sync.get("/commands/", response_model=list[CommandSchema])
def get_commands(skip: int = 0, limit: int = 30, service: CommandService = Depends()):
    return service.get_commands(skip, limit)

@router_sync.get("/commands/{command_id}", response_model=CommandSchema)
def get_command(command_id: UUID, service: CommandService = Depends()):
    return service.get_command(command_id)

@router_sync.get("/commands/name/{name}", response_model=CommandSchema)
def get_command_by_name(name: str, service: CommandService = Depends()):
    return service.get_command_by_name(name)

@router_sync.put("/commands/{command_id}", response_model=CommandSchema)
def update_command(command_id: UUID, command_data: CommandBase, service: CommandService = Depends()):
    return service.update_command(command_id, command_data)

@router_sync.delete("/commands/{command_id}", response_model=CommandSchema)
def delete_command(command_id: UUID, service: CommandService = Depends()):
    return service.delete_command(command_id)

# Asynchronous Endpoints
@router_async.post("/commands/", response_model=CommandSchema)
async def create_command_async(command_data: CommandCreate, service: CommandService = Depends()):
    return await service.create_command_async(command_data)

@router_async.get("/commands/name/{name}", response_model=CommandSchema)
async def get_command_by_name_async(name: str, service: CommandService = Depends()):
    return await service.get_command_by_name_async(name)
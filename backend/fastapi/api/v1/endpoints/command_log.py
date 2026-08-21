from uuid import UUID

from fastapi import APIRouter, Depends

from backend.fastapi.crud import CommandLogService
from backend.fastapi.schemas import CommandLogCreate, CommandLogSchema, CommandLogUpdate

router = APIRouter()


@router.post("/command_logs/", response_model=CommandLogSchema)
async def create_command_log(command_log_data: CommandLogCreate, service: CommandLogService = Depends()):
    return await service.create(command_log_data)


@router.get("/command_logs/", response_model=list[CommandLogSchema])
async def list_command_logs(skip: int = 0, limit: int = 30, service: CommandLogService = Depends()):
    return await service.list(skip, limit)


@router.get("/command_logs/{command_log_id}", response_model=CommandLogSchema)
async def get_command_log(command_log_id: UUID, service: CommandLogService = Depends()):
    return await service.get(command_log_id)


@router.put("/command_logs/{command_log_id}", response_model=CommandLogSchema)
async def update_command_log(command_log_id: UUID, command_log_data: CommandLogUpdate, service: CommandLogService = Depends()):
    return await service.update(command_log_id, command_log_data)


@router.delete("/command_logs/{command_log_id}", response_model=CommandLogSchema)
async def delete_command_log(command_log_id: UUID, service: CommandLogService = Depends()):
    return await service.delete(command_log_id)

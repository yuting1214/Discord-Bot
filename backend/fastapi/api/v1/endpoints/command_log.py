from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from typing import List

from backend.fastapi.schemas import (
    CommandLogCreate,
    CommandLogUpdate,
    CommandLogSchema
)
from backend.fastapi.crud import (
    CommandLogService
)

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/command_logs/", response_model=CommandLogSchema)
def create_command_log(command_log_data: CommandLogCreate, service: CommandLogService = Depends()):
    return service.create_command_log(command_log_data)

@router_sync.get("/command_logs/", response_model=List[CommandLogSchema])
def get_command_logs(skip: int = 0, limit: int = 30, service: CommandLogService = Depends()):
    return service.get_command_logs(skip, limit)

@router_sync.get("/command_logs/{command_log_id}", response_model=CommandLogSchema)
def get_command_log(command_log_id: UUID, service: CommandLogService = Depends()):
    return service.get_command_log(command_log_id)

@router_sync.put("/command_logs/{command_log_id}", response_model=CommandLogSchema)
def update_command_log(command_log_id: UUID, command_log_data: CommandLogUpdate, service: CommandLogService = Depends()):
    return service.update_command_log(command_log_id, command_log_data)

@router_sync.delete("/command_logs/{command_log_id}", response_model=CommandLogSchema)
def delete_command_log(command_log_id: UUID, service: CommandLogService = Depends()):
    return service.delete_command_log(command_log_id)

# Asynchronous Endpoints
@router_async.post("/command_logs/", response_model=CommandLogSchema)
async def create_command_log_async(command_log_data: CommandLogCreate, service: CommandLogService = Depends()):
    return await service.create_command_log_async(command_log_data)

@router_async.delete("/command_logs/{command_log_id}", response_model=CommandLogSchema)
def delete_command_log_async(command_log_id: UUID, service: CommandLogService = Depends()):
    return service.delete_command_log_async(command_log_id)
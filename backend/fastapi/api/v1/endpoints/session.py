from fastapi import APIRouter, Depends
from uuid import UUID
from typing import List
from backend.fastapi.schemas import (
    SessionCreate,
    SessionUpdate,
    SessionSchema
)
from backend.fastapi.crud import (
    SessionService
)

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/sessions/", response_model=SessionSchema)
def create_session(session_data: SessionCreate, service: SessionService = Depends()):
    return service.create_session(session_data)

@router_sync.get("/sessions/", response_model=List[SessionSchema])
def get_sessions(skip: int = 0, limit: int = 30, service: SessionService = Depends()):
    return service.get_sessions(skip, limit)

@router_sync.get("/sessions/{session_id}", response_model=SessionSchema)
def get_session(session_id: UUID, service: SessionService = Depends()):
    return service.get_session(session_id)

@router_sync.get("/sessions/current/single/", response_model=SessionSchema)
def get_current_single_session(user_id: UUID, service: SessionService = Depends()):
    return service.get_current_single_session(user_id)

@router_sync.get("/sessions/current/group/", response_model=SessionSchema)
def get_current_group_session(channel_discord_id: str, service: SessionService = Depends()):
    return service.get_current_group_session(channel_discord_id)

@router_sync.get("/sessions/active/single/", response_model=List[SessionSchema])
def get_active_single_sessions(user_id: UUID, service: SessionService = Depends()):
    return service.get_active_single_sessions(user_id)

@router_sync.get("/sessions/active/group/", response_model=List[SessionSchema])
def get_active_group_sessions(channel_discord_id: str, service: SessionService = Depends()):
    return service.get_active_group_sessions(channel_discord_id)

@router_sync.put("/sessions/{session_id}", response_model=SessionSchema)
def update_session(session_id: UUID, session_data: SessionUpdate, service: SessionService = Depends()):
    return service.update_session(session_id, session_data)

@router_sync.delete("/sessions/{session_id}", response_model=SessionSchema)
def delete_session(session_id: UUID, service: SessionService = Depends()):
    return service.delete_session(session_id)

# Asynchronous Endpoints
@router_async.post("/sessions/", response_model=SessionSchema)
async def create_session_async(session_data: SessionCreate, service: SessionService = Depends()):
    return await service.create_session_async(session_data)

@router_async.get("/sessions/{session_id}", response_model=SessionSchema)
async def get_session_async(session_id: UUID, service: SessionService = Depends()):
    return await service.get_session_async(session_id)

@router_async.get("/sessions/current/single/", response_model=SessionSchema)
async def get_current_single_session_async(user_id: UUID, service: SessionService = Depends()):
    return await service.get_current_single_session_async(user_id)

@router_async.get("/sessions/current/group/", response_model=SessionSchema)
async def get_current_group_session_async(channel_discord_id: str, service: SessionService = Depends()):
    return await service.get_current_group_session_async(channel_discord_id)

@router_async.get("/sessions/active/single/", response_model=List[SessionSchema])
async def get_active_single_sessions_async(user_id: UUID, service: SessionService = Depends()):
    return await service.get_active_single_sessions_async(user_id)

@router_async.get("/sessions/active/group/", response_model=List[SessionSchema])
async def get_active_group_sessions_async(channel_discord_id: str, service: SessionService = Depends()):
    return await service.get_active_group_sessions_async(channel_discord_id)

@router_async.put("/sessions/{session_id}", response_model=SessionSchema)
async def update_session_async(session_id: UUID, session_data: SessionUpdate, service: SessionService = Depends()):
    return await service.update_session_async(session_id, session_data)

@router_async.delete("/sessions/{session_id}", response_model=SessionSchema)
async def delete_session_async(session_id: UUID, service: SessionService = Depends()):
    return service.delete_session_async(session_id)
from uuid import UUID

from fastapi import APIRouter, Depends

from src.backend.fastapi.crud import SessionService
from src.backend.fastapi.schemas import SessionCreate, SessionSchema, SessionUpdate

router = APIRouter()


@router.post("/sessions/", response_model=SessionSchema)
async def create_session(session_data: SessionCreate, service: SessionService = Depends()):
    return await service.create(session_data)


@router.get("/sessions/", response_model=list[SessionSchema])
async def list_sessions(skip: int = 0, limit: int = 30, service: SessionService = Depends()):
    return await service.list(skip, limit)


@router.get("/sessions/{session_id}", response_model=SessionSchema)
async def get_session(session_id: UUID, service: SessionService = Depends()):
    return await service.get(session_id)


@router.put("/sessions/{session_id}", response_model=SessionSchema)
async def update_session(session_id: UUID, session_data: SessionUpdate, service: SessionService = Depends()):
    return await service.update(session_id, session_data)


@router.delete("/sessions/{session_id}", response_model=SessionSchema)
async def delete_session(session_id: UUID, service: SessionService = Depends()):
    return await service.delete(session_id)


@router.get("/sessions/active/single/", response_model=list[SessionSchema])
async def get_active_single_sessions(user_id: UUID, service: SessionService = Depends()):
    return await service.get_active_single(user_id)


@router.get("/sessions/active/group/", response_model=list[SessionSchema])
async def get_active_group_sessions(channel_discord_id: str, service: SessionService = Depends()):
    return await service.get_active_group(channel_discord_id)

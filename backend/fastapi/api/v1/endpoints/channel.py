from fastapi import APIRouter, Depends, Query, HTTPException
from uuid import UUID
from typing import List, Optional
from backend.fastapi.schemas import (
    ChannelCreate,
    ChannelUpdate,
    ChannelSchema
)
from backend.fastapi.crud import (
    ChannelService
)

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/channels/", response_model=ChannelSchema)
def create_channel(channel_data: ChannelCreate, service: ChannelService = Depends()):
    return service.create_channel(channel_data)

@router_sync.get("/channels/", response_model=List[ChannelSchema])
def get_channels(skip: int = 0, limit: int = 30, service: ChannelService = Depends()):
    return service.get_channels(skip, limit)

@router_sync.get("/channel/", response_model=ChannelSchema)
def get_channel(
    channel_discord_id: str, 
    is_group: bool, 
    user_id: Optional[UUID] = Query(None),
    service: ChannelService = Depends()
):
    return service.get_channel_by_channel_discord_id_and_group_status(channel_discord_id, is_group, user_id)

@router_sync.put("/channels/{channel_id}", response_model=ChannelSchema)
def update_channel(channel_id: UUID, channel_data: ChannelUpdate, service: ChannelService = Depends()):
    return service.update_channel(channel_id, channel_data)

@router_sync.delete("/channels/{channel_id}", response_model=ChannelSchema)
def delete_channel(channel_id: UUID, service: ChannelService = Depends()):
    return service.delete_channel(channel_id)

# Asynchronous Endpoints
@router_async.post("/channels/", response_model=ChannelSchema)
async def create_channel_async(channel_data: ChannelCreate, service: ChannelService = Depends()):
    return await service.create_channel_async(channel_data)

@router_async.delete("/channels/{channel_id}", response_model=ChannelSchema)
def delete_channel_async(channel_id: UUID, service: ChannelService = Depends()):
    return service.delete_channel_async(channel_id)
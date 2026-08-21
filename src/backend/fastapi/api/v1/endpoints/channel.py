from uuid import UUID

from fastapi import APIRouter, Depends

from src.backend.fastapi.crud import ChannelService
from src.backend.fastapi.schemas import ChannelCreate, ChannelSchema, ChannelUpdate

router = APIRouter()


@router.post("/channels/", response_model=ChannelSchema)
async def create_channel(channel_data: ChannelCreate, service: ChannelService = Depends()):
    return await service.create(channel_data)


@router.get("/channels/", response_model=list[ChannelSchema])
async def list_channels(skip: int = 0, limit: int = 30, service: ChannelService = Depends()):
    return await service.list(skip, limit)


@router.get("/channels/{channel_id}", response_model=ChannelSchema)
async def get_channel(channel_id: UUID, service: ChannelService = Depends()):
    return await service.get(channel_id)


@router.put("/channels/{channel_id}", response_model=ChannelSchema)
async def update_channel(channel_id: UUID, channel_data: ChannelUpdate, service: ChannelService = Depends()):
    return await service.update(channel_id, channel_data)


@router.delete("/channels/{channel_id}", response_model=ChannelSchema)
async def delete_channel(channel_id: UUID, service: ChannelService = Depends()):
    return await service.delete(channel_id)


@router.get("/channel/", response_model=ChannelSchema | None)
async def get_channel_by_discord_id(
    channel_discord_id: str,
    is_group: bool,
    user_id: UUID | None = None,
    service: ChannelService = Depends(),
):
    return await service.get_by_channel_discord_id(channel_discord_id, is_group, user_id)

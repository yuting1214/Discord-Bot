from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.backend.constants import MEMORY_WINDOW_SIZE
from src.backend.fastapi.crud import MessageService
from src.backend.fastapi.schemas import MessageBase, MessageCreate, MessageSchema

router = APIRouter()


@router.post("/messages/", response_model=MessageSchema)
async def create_message(message_data: MessageCreate, service: MessageService = Depends()):
    return await service.create(message_data)


@router.get("/messages/", response_model=list[MessageSchema])
async def list_messages(skip: int = 0, limit: int = 30, service: MessageService = Depends()):
    return await service.list(skip, limit)


@router.get("/messages/{message_id}", response_model=MessageSchema)
async def get_message(message_id: UUID, service: MessageService = Depends()):
    return await service.get(message_id)


@router.put("/messages/{message_id}", response_model=MessageSchema)
async def update_message(message_id: UUID, message_data: MessageBase, service: MessageService = Depends()):
    return await service.update(message_id, message_data)


@router.delete("/messages/{message_id}", response_model=MessageSchema)
async def delete_message(message_id: UUID, service: MessageService = Depends()):
    return await service.delete(message_id)


@router.get("/messages/latest/", response_model=list[MessageSchema])
async def get_latest_messages(session_id: UUID, n: int = MEMORY_WINDOW_SIZE, service: MessageService = Depends()):
    return await service.get_latest(session_id, n)


@router.get("/messages/conversations/", response_model=list[MessageSchema])
async def get_messages_by_conversations(
    conversation_ids: list[UUID] = Query(...), service: MessageService = Depends()
):
    return await service.get_by_conversations(conversation_ids)

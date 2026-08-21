from fastapi import APIRouter, Depends, Query
from uuid import UUID
from typing import List
from backend.constants import MEMORY_WINDOW_SIZE
from backend.fastapi.schemas import (
    MessageCreate,
    MessageBase,
    MessageSchema
)
from backend.fastapi.crud import (
    MessageService
)

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/messages/", response_model=MessageSchema)
def create_message(message_data: MessageCreate, service: MessageService = Depends()):
    return service.create_message(message_data)

@router_sync.get("/messages/", response_model=List[MessageSchema])
def get_messages(skip: int = 0, limit: int = 30, service: MessageService = Depends()):
    return service.get_messages(skip, limit)

@router_sync.get("/messages/{message_id}", response_model=MessageSchema)
def get_message(message_id: UUID, service: MessageService = Depends()):
    return service.get_message(message_id)

@router_sync.get("/messages/latest/", response_model=List[MessageSchema])
def get_latest_messages(session_id: UUID, n: int = MEMORY_WINDOW_SIZE, service: MessageService = Depends()):
    return service.get_latest_messages(session_id, n)

@router_sync.get("/messages/conversations/", response_model=List[MessageSchema])
def get_messages_by_conversations(conversation_ids: List[UUID] = Query(...), service: MessageService = Depends()):
    return service.get_messages_by_conversations(conversation_ids)

@router_sync.put("/messages/{message_id}", response_model=MessageSchema)
def update_message(message_id: UUID, message_data: MessageBase, service: MessageService = Depends()):
    return service.update_message(message_id, message_data)

@router_sync.delete("/messages/{message_id}", response_model=MessageSchema)
def delete_message(message_id: UUID, service: MessageService = Depends()):
    return service.delete_message(message_id)

# Asynchronous Endpoints
@router_async.post("/messages/", response_model=MessageSchema)
def create_message_async(message_data: MessageCreate, service: MessageService = Depends()):
    return service.create_message_async(message_data)

@router_async.get("/messages/latest/", response_model=List[MessageSchema])
async def get_latest_messages_async(session_id: UUID, n: int = MEMORY_WINDOW_SIZE, service: MessageService = Depends()):
    return await service.get_latest_messages_async(session_id, n)

@router_async.get("/messages/conversations/", response_model=List[MessageSchema])
async def get_messages_by_conversations_async(conversation_ids: List[UUID] = Query(...), service: MessageService = Depends()):
    return await service.get_messages_by_conversations_async(conversation_ids)

@router_async.put("/messages/{message_id}", response_model=MessageSchema)
async def update_message_async(message_id: UUID, message_data: MessageBase, service: MessageService = Depends()):
    return await service.update_message_async(message_id, message_data)

@router_async.delete("/messages/{message_id}", response_model=MessageSchema)
def delete_message_async(message_id: UUID, service: MessageService = Depends()):
    return service.delete_message_async(message_id)

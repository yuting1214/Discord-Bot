from fastapi import APIRouter, Depends
from uuid import UUID
from typing import List

from backend.fastapi.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationSchema
)
from backend.fastapi.crud import (
    ConversationService
)

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/conversations/", response_model=ConversationSchema)
def create_conversation(conversation_data: ConversationCreate, service: ConversationService = Depends()):
    return service.create_conversation(conversation_data)

@router_sync.get("/conversations/", response_model=List[ConversationSchema])
def get_conversations(skip: int = 0, limit: int = 30, service: ConversationService = Depends()):
    return service.get_conversations(skip, limit)

@router_sync.get("/conversations/{conversation_id}", response_model=ConversationSchema)
def get_conversation(conversation_id: UUID, service: ConversationService = Depends()):
    return service.get_conversation(conversation_id)

@router_sync.put("/conversations/{conversation_id}", response_model=ConversationSchema)
def update_conversation(conversation_id: UUID, conversation_data: ConversationUpdate, service: ConversationService = Depends()):
    return service.update_conversation(conversation_id, conversation_data)

@router_sync.delete("/conversations/{conversation_id}", response_model=ConversationSchema)
def delete_conversation(conversation_id: UUID, service: ConversationService = Depends()):
    return service.delete_conversation(conversation_id)

# Asynchronous Endpoints
@router_async.post("/conversations/", response_model=ConversationSchema)
async def create_conversation_async(conversation_data: ConversationCreate, service: ConversationService = Depends()):
    return await service.create_conversation_async(conversation_data)

@router_async.get("/conversations/{conversation_id}", response_model=ConversationSchema)
async def get_conversation_async(conversation_id: UUID, service: ConversationService = Depends()):
    return await service.get_conversation_async(conversation_id)

@router_async.put("/conversations/{conversation_id}", response_model=ConversationSchema)
async def update_conversation_async(conversation_id: UUID, conversation_data: ConversationUpdate, service: ConversationService = Depends()):
    return await service.update_conversation_async(conversation_id, conversation_data)

@router_async.delete("/conversations/{conversation_id}", response_model=ConversationSchema)
def delete_conversation_async(conversation_id: UUID, service: ConversationService = Depends()):
    return service.delete_conversation_async(conversation_id)

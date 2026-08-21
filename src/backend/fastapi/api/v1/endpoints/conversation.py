from uuid import UUID

from fastapi import APIRouter, Depends

from src.backend.fastapi.crud import ConversationService
from src.backend.fastapi.schemas import ConversationCreate, ConversationSchema, ConversationUpdate

router = APIRouter()


@router.post("/conversations/", response_model=ConversationSchema)
async def create_conversation(conversation_data: ConversationCreate, service: ConversationService = Depends()):
    return await service.create(conversation_data)


@router.get("/conversations/", response_model=list[ConversationSchema])
async def list_conversations(skip: int = 0, limit: int = 30, service: ConversationService = Depends()):
    return await service.list(skip, limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationSchema)
async def get_conversation(conversation_id: UUID, service: ConversationService = Depends()):
    return await service.get(conversation_id)


@router.put("/conversations/{conversation_id}", response_model=ConversationSchema)
async def update_conversation(conversation_id: UUID, conversation_data: ConversationUpdate, service: ConversationService = Depends()):
    return await service.update(conversation_id, conversation_data)


@router.delete("/conversations/{conversation_id}", response_model=ConversationSchema)
async def delete_conversation(conversation_id: UUID, service: ConversationService = Depends()):
    return await service.delete(conversation_id)

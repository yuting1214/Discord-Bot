
from typing import List, Optional
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.fastapi.dependencies.database import get_sync_db, get_async_db
from backend.fastapi.models import Conversation
from backend.fastapi.schemas import (
    ConversationUpdate, ConversationCreate
)

class ConversationService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_conversation(self, conversation_data: ConversationCreate) -> Conversation:
        db_conversation = Conversation(**conversation_data.model_dump())
        self.db_sync.add(db_conversation)
        self.db_sync.commit()
        self.db_sync.refresh(db_conversation)
        return db_conversation
    
    async def create_conversation_async(self, conversation_data: ConversationCreate) -> Conversation:
        db_conversation = Conversation(**conversation_data.model_dump())
        self.db_async.add(db_conversation)
        await self.db_async.commit()
        await self.db_async.refresh(db_conversation)
        return db_conversation

    def get_conversations(self, skip: int = 0, limit: int = 30) -> List[Conversation]:
        return self.db_sync.query(Conversation).offset(skip).limit(limit).all()

    def get_conversation(self, conversation_id: UUID) -> Conversation:
        db_conversation = self.db_sync.query(Conversation).filter(Conversation.id == conversation_id).first()
        if db_conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return db_conversation
    
    async def get_conversation_async(self, conversation_id: UUID) -> Conversation:
        stmt = select(Conversation).filter(Conversation.id == conversation_id)
        result = await self.db_async.execute(stmt)
        db_conversation = result.scalars().first()
        
        if db_conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        return db_conversation

    def update_conversation(self, conversation_id: UUID, conversation_data: ConversationUpdate) -> Conversation:
        db_conversation = self.db_sync.query(Conversation).filter(Conversation.id == conversation_id).first()
        if db_conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        for key, value in conversation_data.model_dump(exclude_unset=True).items():
            setattr(db_conversation, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_conversation)
        return db_conversation
    
    async def update_conversation_async(self, conversation_id: UUID, conversation_data: ConversationUpdate) -> Conversation:
        stmt = select(Conversation).filter(Conversation.id == conversation_id)
        result = await self.db_async.execute(stmt)
        db_conversation = result.scalars().first()
        
        if db_conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        for key, value in conversation_data.model_dump(exclude_unset=True).items():
            setattr(db_conversation, key, value)
        
        await self.db_async.commit()
        await self.db_async.refresh(db_conversation)
        
        return db_conversation

    def delete_conversation(self, conversation_id: UUID) -> Conversation:
        db_conversation = self.db_sync.query(Conversation).filter(Conversation.id == conversation_id).first()
        if db_conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        self.db_sync.delete(db_conversation)
        self.db_sync.commit()
        return db_conversation
    
    async def delete_conversation_async(self, conversation_id: UUID) -> Conversation:
        stmt = select(Conversation).filter(Conversation.id == conversation_id)
        result = await self.db_async.execute(stmt)
        db_conversation = result.scalars().first()

        if db_conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        await self.db_async.delete(db_conversation)
        await self.db_async.commit()
        return db_conversation
from typing import List
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy import case, select, desc, asc
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.fastapi.dependencies.database import get_sync_db, get_async_db
from backend.fastapi.models import Message, Conversation
from backend.constants import MEMORY_WINDOW_SIZE
from backend.fastapi.schemas import (
    MessageBase, MessageCreate
)

class MessageService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_message(self, message_data: MessageCreate) -> Message:
        db_message = Message(**message_data.model_dump())
        self.db_sync.add(db_message)
        self.db_sync.commit()
        self.db_sync.refresh(db_message)
        return db_message
    
    async def create_message_async(self, message_data: MessageCreate) -> Message:
        db_message = Message(**message_data.model_dump())
        self.db_async.add(db_message)
        await self.db_async.commit()
        await self.db_async.refresh(db_message)
        return db_message

    def get_messages(self, skip: int = 0, limit: int = 30) -> List[Message]:
        return self.db_sync.query(Message).offset(skip).limit(limit).all()

    def get_message(self, message_id: UUID) -> Message:
        db_message = self.db_sync.query(Message).filter(Message.id == message_id).first()
        if db_message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        return db_message
    
    def get_latest_messages(self, session_id: UUID, n: int = MEMORY_WINDOW_SIZE) -> List[Message]:
        # Fetch conversations associated with the given session_id
        conversations = self.db_sync.query(Conversation).filter(
            Conversation.session_id == session_id,
            ).order_by(Conversation.start_time.desc()).limit(n).all()
        conversation_ids = [conversation.id for conversation in conversations]

        # Generate a SQL CASE statement to preserve the order of conversation_ids
        case_statement = case(
            *(
                (Message.conversation_id == conversation_id, index)
                for index, conversation_id in enumerate(conversation_ids)
            ),
            else_=len(conversation_ids)  # A default value that ensures unmatched rows are at the end
        )

        # Fetch messages associated with the conversation_ids, ordered by the conversation_id order and creation time
        return self.db_sync.query(Message).filter(
            Message.conversation_id.in_(conversation_ids),
        ).order_by(case_statement, Message.timestamp.desc()).all()

    async def get_latest_messages_async(self, session_id: UUID, n: int = MEMORY_WINDOW_SIZE) -> List[Message]:
        # Fetch conversations associated with the given session_id
        stmt = select(Conversation).filter(
            Conversation.session_id == session_id
        ).order_by(desc(Conversation.start_time)).limit(n)
        
        result = await self.db_async.execute(stmt)
        conversations = result.scalars().all()
        conversation_ids = [conversation.id for conversation in conversations]

        # Generate a SQL CASE statement to preserve the order of conversation_ids
        case_statement = case(
            *(
                (Message.conversation_id == conversation_id, index)
                for index, conversation_id in enumerate(conversation_ids)
            ),
            else_=len(conversation_ids)  # A default value that ensures unmatched rows are at the end
        )

        # Fetch messages associated with the conversation_ids, ordered by the conversation_id order and creation time
        stmt = select(Message).filter(
            Message.conversation_id.in_(conversation_ids)
        ).order_by(case_statement, desc(Message.timestamp))
        
        result = await self.db_async.execute(stmt)
        return result.scalars().all() 
    
    def get_messages_by_conversations(self, conversation_ids: List[UUID]) -> List[Message]:
        # Generate a SQL CASE statement to preserve the order of conversation_ids
        case_statement = case(
            *(
                (Message.conversation_id == conversation_id, index)
                for index, conversation_id in enumerate(conversation_ids)
            ),
            else_=len(conversation_ids)  # A default value that ensures unmatched rows are at the end
        )
        return self.db_sync.query(Message).filter(
            Message.conversation_id.in_(conversation_ids)
        ).order_by(case_statement, Message.timestamp.asc()).all()
    
    async def get_messages_by_conversations_async(self, conversation_ids: List[UUID]) -> List[Message]:
            # Generate a SQL CASE statement to preserve the order of conversation_ids
            case_statement = case(
                *(
                    (Message.conversation_id == conversation_id, index)
                    for index, conversation_id in enumerate(conversation_ids)
                ),
                else_=len(conversation_ids)  # A default value that ensures unmatched rows are at the end
            )
            
            stmt = select(Message).filter(
                Message.conversation_id.in_(conversation_ids)
            ).order_by(case_statement, asc(Message.timestamp))
            
            result = await self.db_async.execute(stmt)
            return result.scalars().all()

    def update_message(self, message_id: UUID, message_data: MessageBase) -> Message:
        db_message = self.db_sync.query(Message).filter(Message.id == message_id).first()
        if db_message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        for key, value in message_data.model_dump(exclude_unset=True).items():
            setattr(db_message, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_message)
        return db_message
    
    async def update_message_async(self, message_id: UUID, message_data: MessageBase) -> Message:
        stmt = select(Message).filter(Message.id == message_id)
        result = await self.db_async.execute(stmt)
        db_message = result.scalars().first()
        
        if db_message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        
        for key, value in message_data.model_dump(exclude_unset=True).items():
            setattr(db_message, key, value)
        
        await self.db_async.commit()
        await self.db_async.refresh(db_message)
        
        return db_message

    def delete_message(self, message_id: UUID) -> Message:
        db_message = self.db_sync.query(Message).filter(Message.id == message_id).first()
        if db_message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        self.db_sync.delete(db_message)
        self.db_sync.commit()
        return db_message

    async def delete_message_async(self, message_id: UUID) -> Message:
        stmt = select(Message).filter(Message.id == message_id)
        result = await self.db_async.execute(stmt)
        db_message = result.scalars().first()

        if db_message is None:
            raise HTTPException(status_code=404, detail="Message not found")

        await self.db_async.delete(db_message)
        await self.db_async.commit()
        return db_message
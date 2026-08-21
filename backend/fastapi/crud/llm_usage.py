from typing import List
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.fastapi.dependencies.database import get_sync_db, get_async_db
from backend.fastapi.models import LLMUsage
from backend.fastapi.schemas import (
    LLMUsageUpdate, LLMUsageCreate
)

class LLMUsageService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_llm_usage(self, llm_usage_data: LLMUsageCreate) -> LLMUsage:
        db_llm_usage = LLMUsage(**llm_usage_data.model_dump())
        self.db_sync.add(db_llm_usage)
        self.db_sync.commit()
        self.db_sync.refresh(db_llm_usage)
        return db_llm_usage
    
    async def create_llm_usage_async(self, llm_usage_data: LLMUsageCreate) -> LLMUsage:
        db_llm_usage = LLMUsage(**llm_usage_data.model_dump())
        self.db_async.add(db_llm_usage)
        await self.db_async.commit()
        await self.db_async.refresh(db_llm_usage)
        return db_llm_usage

    def get_llm_usages(self, skip: int = 0, limit: int = 30) -> List[LLMUsage]:
        return self.db_sync.query(LLMUsage).offset(skip).limit(limit).all()

    def get_llm_usage(self, llm_usage_id: UUID) -> LLMUsage:
        db_llm_usage = self.db_sync.query(LLMUsage).filter(LLMUsage.id == llm_usage_id).first()
        if db_llm_usage is None:
            raise HTTPException(status_code=404, detail="LLMUsage not found")
        return db_llm_usage

    def update_llm_usage(self, llm_usage_id: UUID, llm_usage_data: LLMUsageUpdate) -> LLMUsage:
        db_llm_usage = self.db_sync.query(LLMUsage).filter(LLMUsage.id == llm_usage_id).first()
        if db_llm_usage is None:
            raise HTTPException(status_code=404, detail="LLMUsage not found")
        for key, value in llm_usage_data.model_dump(exclude_unset=True).items():
            setattr(db_llm_usage, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_llm_usage)
        return db_llm_usage

    def delete_llm_usage(self, llm_usage_id: UUID) -> LLMUsage:
        db_llm_usage = self.db_sync.query(LLMUsage).filter(LLMUsage.id == llm_usage_id).first()
        if db_llm_usage is None:
            raise HTTPException(status_code=404, detail="LLMUsage not found")
        self.db_sync.delete(db_llm_usage)
        self.db_sync.commit()
        return db_llm_usage
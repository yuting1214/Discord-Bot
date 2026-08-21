from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.fastapi.dependencies.database import get_async_db, get_sync_db
from backend.fastapi.models import LLM
from backend.fastapi.schemas import LLMBase, LLMCreate


class LLMService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_llm(self, llm_data: LLMCreate) -> LLM:
        db_llm = LLM(**llm_data.model_dump())
        self.db_sync.add(db_llm)
        self.db_sync.commit()
        self.db_sync.refresh(db_llm)
        return db_llm
    
    async def create_llm_async(self, llm_data: LLMCreate) -> LLM:
        db_llm = LLM(**llm_data.model_dump())
        self.db_async.add(db_llm)
        await self.db_async.commit()
        await self.db_async.refresh(db_llm)
        return db_llm

    def get_llms(self, skip: int = 0, limit: int = 30) -> list[LLM]:
        return self.db_sync.query(LLM).offset(skip).limit(limit).all()

    def get_llm(self, llm_id: UUID) -> LLM:
        db_llm = self.db_sync.query(LLM).filter(LLM.id == llm_id).first()
        if db_llm is None:
            raise HTTPException(status_code=404, detail="LLM not found")
        return db_llm

    def update_llm(self, llm_id: UUID, llm_data: LLMBase) -> LLM:
        db_llm = self.db_sync.query(LLM).filter(LLM.id == llm_id).first()
        if db_llm is None:
            raise HTTPException(status_code=404, detail="LLM not found")
        for key, value in llm_data.model_dump(exclude_unset=True).items():
            setattr(db_llm, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_llm)
        return db_llm

    def delete_llm(self, llm_id: UUID) -> LLM:
        db_llm = self.db_sync.query(LLM).filter(LLM.id == llm_id).first()
        if db_llm is None:
            raise HTTPException(status_code=404, detail="LLM not found")
        self.db_sync.delete(db_llm)
        self.db_sync.commit()
        return db_llm

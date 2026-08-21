from typing import List, Optional
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.fastapi.dependencies.database import get_sync_db, get_async_db
from backend.fastapi.models import CommandLog
from backend.fastapi.schemas import (
    CommandLogUpdate, CommandLogCreate
)

class CommandLogService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_command_log(self, command_log_data: CommandLogCreate) -> CommandLog:
        db_command_log = CommandLog(**command_log_data.model_dump())
        self.db_sync.add(db_command_log)
        self.db_sync.commit()
        self.db_sync.refresh(db_command_log)
        return db_command_log
    
    async def create_command_log_async(self, command_log_data: CommandLogCreate) -> CommandLog:
        db_command_log = CommandLog(**command_log_data.model_dump())
        self.db_async.add(db_command_log)
        await self.db_async.commit()
        await self.db_async.refresh(db_command_log)
        return db_command_log

    def get_command_logs(self, skip: int = 0, limit: int = 30) -> List[CommandLog]:
        return self.db_sync.query(CommandLog).offset(skip).limit(limit).all()

    def get_command_log(self, command_log_id: UUID) -> CommandLog:
        db_command_log = self.db_sync.query(CommandLog).filter(CommandLog.id == command_log_id).first()
        if db_command_log is None:
            raise HTTPException(status_code=404, detail="CommandLog not found")
        return db_command_log
    
    def update_command_log(self, command_log_id: UUID, command_log_data: CommandLogUpdate) -> CommandLog:
        db_command_log = self.db_sync.query(CommandLog).filter(CommandLog.id == command_log_id).first()
        if db_command_log is None:
            raise HTTPException(status_code=404, detail="CommandLog not found")
        for key, value in command_log_data.model_dump(exclude_unset=True).items():
            setattr(db_command_log, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_command_log)
        return db_command_log

    def delete_command_log(self, command_log_id: UUID) -> CommandLog:
        db_command_log = self.db_sync.query(CommandLog).filter(CommandLog.id == command_log_id).first()
        if db_command_log is None:
            raise HTTPException(status_code=404, detail="CommandLog not found")
        self.db_sync.delete(db_command_log)
        self.db_sync.commit()
        return db_command_log
    
    async def delete_command_log_async(self, command_log_id: UUID) -> CommandLog:
        stmt = select(CommandLog).filter(CommandLog.id == command_log_id)
        result = await self.db_async.execute(stmt)
        db_command_log = result.scalars().first()

        if db_command_log is None:
            raise HTTPException(status_code=404, detail="CommandLog not found")

        await self.db_async.delete(db_command_log)
        await self.db_async.commit()
        return db_command_log

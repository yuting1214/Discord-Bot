from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.fastapi.dependencies.database import get_async_db, get_sync_db
from backend.fastapi.models import Command
from backend.fastapi.schemas import CommandBase, CommandCreate


class CommandService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_command(self, command_data: CommandCreate) -> Command:
        db_command = Command(**command_data.model_dump())
        self.db_sync.add(db_command)
        self.db_sync.commit()
        self.db_sync.refresh(db_command)
        return db_command
    
    async def create_command_async(self, command_data: CommandCreate) -> Command:
        db_command = Command(**command_data.model_dump())
        self.db_async.add(db_command)
        await self.db_async.commit()
        await self.db_async.refresh(db_command)
        return db_command

    def get_commands(self, skip: int = 0, limit: int = 30) -> list[Command]:
        return self.db_sync.query(Command).offset(skip).limit(limit).all()

    def get_command(self, command_id: UUID) -> Command:
        db_command = self.db_sync.query(Command).filter(Command.id == command_id).first()
        if db_command is None:
            raise HTTPException(status_code=404, detail="Command not found")
        return db_command
    
    def get_command_by_name(self, name: str) -> Command:
        db_command = self.db_sync.query(Command).filter(Command.name == name).first()
        if db_command is None:
            raise HTTPException(status_code=404, detail=f"Command '{name}' not found")
        return db_command
    
    async def get_command_by_name_async(self, name: str) -> Command:
        stmt = select(Command).filter(Command.name == name)
        result = await self.db_async.execute(stmt)
        db_command = result.scalars().first()
        
        if db_command is None:
            raise HTTPException(status_code=404, detail=f"Command '{name}' not found")
        
        return db_command

    def update_command(self, command_id: UUID, command_data: CommandBase) -> Command:
        db_command = self.db_sync.query(Command).filter(Command.id == command_id).first()
        if db_command is None:
            raise HTTPException(status_code=404, detail="Command not found")
        for key, value in command_data.model_dump(exclude_unset=True).items():
            setattr(db_command, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_command)
        return db_command

    def delete_command(self, command_id: UUID) -> Command:
        db_command = self.db_sync.query(Command).filter(Command.id == command_id).first()
        if db_command is None:
            raise HTTPException(status_code=404, detail="Command not found")
        self.db_sync.delete(db_command)
        self.db_sync.commit()
        return db_command
    
async def create_init_command_async(db: AsyncSession, command_data: dict):
    # Check if the command already exists
    stmt = select(Command).filter_by(name=command_data["name"])
    result = await db.execute(stmt)
    existing_command = result.scalars().first()
    if existing_command:
        return existing_command

    # If not, insert the new model asynchronously
    db_command = Command(**command_data)
    db.add(db_command)
    await db.commit() 
    await db.refresh(db_command) 
    return db_command
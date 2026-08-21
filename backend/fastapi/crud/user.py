from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from backend.fastapi.dependencies.database import get_async_db, get_sync_db
from backend.fastapi.models import Session as SessionModel  # noqa: F401
from backend.fastapi.models import User
from backend.fastapi.schemas import UserBase, UserCreate


class UserService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_user(self, user_data: UserCreate) -> User:
        db_user = User(**user_data.model_dump())
        self.db_sync.add(db_user)
        self.db_sync.commit()
        self.db_sync.refresh(db_user)
        return db_user
    
    async def create_user_async(self, user_data: UserCreate) -> User:
        db_user = User(**user_data.model_dump())
        self.db_async.add(db_user)
        await self.db_async.commit()
        await self.db_async.refresh(db_user)
        return db_user

    def get_users(self, skip: int = 0, limit: int = 30) -> list[User]:
        return self.db_sync.query(User).offset(skip).limit(limit).all()

    def get_user(self, user_id: UUID) -> User:
        db_user = self.db_sync.query(User).filter(User.id == user_id).first()
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return db_user
    
    async def get_user_async(self, user_id: UUID) -> User:
        stmt = select(User).filter(User.id == user_id)
        
        result = await self.db_async.execute(stmt)
        db_user = result.scalars().first()
        
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        
        return db_user
    
    def get_user_by_discord_id(self, discord_id: str) -> User:
        db_user = self.db_sync.query(User).filter(User.discord_id == discord_id).first()
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return db_user
    
    async def get_user_by_discord_id_async(self, discord_id: str) -> User:
        stmt = select(User).filter(User.discord_id == discord_id)
        
        result = await self.db_async.execute(stmt)
        db_user = result.scalars().first()
        
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        
        return db_user

    def update_user(self, user_id: UUID, user_data: UserBase) -> User:
        db_user = self.db_sync.query(User).filter(User.id == user_id).first()
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        for key, value in user_data.model_dump(exclude_unset=True).items():
            setattr(db_user, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_user)
        return db_user

    def delete_user(self, user_id: UUID) -> User:
        db_user = self.db_sync.query(User).filter(User.id == user_id).first()
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        self.db_sync.delete(db_user)
        self.db_sync.commit()
        return db_user
    
    async def delete_user_async(self, user_id: UUID) -> User:
        stmt = select(User).options(joinedload(User.sessions)).filter(User.id == user_id)
        
        result = await self.db_async.execute(stmt)
        db_user = result.scalars().first()
        
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")
        
        await self.db_async.delete(db_user)
        await self.db_async.commit()
        
        return db_user
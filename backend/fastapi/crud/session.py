from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.fastapi.dependencies.database import get_async_db, get_sync_db
from backend.fastapi.models import Session as SessionModel
from backend.fastapi.models import User
from backend.fastapi.schemas import SessionBase, SessionCreate


class SessionService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async

    def create_session(self, session_data: SessionCreate) -> SessionModel:
        session_dict = session_data.model_dump()
        
        # Fetch the User instances
        if session_data.users:
            user_ids = session_data.users
            users = self.db_sync.query(User).filter(User.id.in_(user_ids)).all()
            if len(users) != len(user_ids):
                raise HTTPException(status_code=404, detail="One or more users not found")
            session_dict['users'] = users
        else:
            session_dict['users'] = []

        db_session = SessionModel(**session_dict)
        self.db_sync.add(db_session)
        self.db_sync.commit()
        self.db_sync.refresh(db_session)
        return db_session
    
    async def create_session_async(self, session_data: SessionCreate) -> SessionModel:
        session_dict = session_data.model_dump()
        
        if session_data.users:
            user_ids = session_data.users
            stmt = select(User).filter(User.id.in_(user_ids))
            result = await self.db_async.execute(stmt)
            users = result.scalars().all()
            
            if len(users) != len(user_ids):
                raise HTTPException(status_code=404, detail="One or more users not found")
            
            session_dict['users'] = users
        else:
            session_dict['users'] = []

        db_session = SessionModel(**session_dict)
        self.db_async.add(db_session)
        await self.db_async.commit()
        await self.db_async.refresh(db_session)
        return db_session

    def get_sessions(self, skip: int = 0, limit: int = 30) -> list[SessionModel]:
        return self.db_sync.query(SessionModel).offset(skip).limit(limit).all()

    def get_session(self, session_id: UUID) -> SessionModel:
        db_session = self.db_sync.query(SessionModel).filter(SessionModel.id == session_id).first()
        if db_session is None:
            raise HTTPException(status_code=404, detail="SessionModel not found")
        return db_session
    
    async def get_session_async(self, session_id: UUID) -> SessionModel:
        stmt = select(SessionModel).filter(SessionModel.id == session_id)
        
        result = await self.db_async.execute(stmt)
        db_session = result.scalars().first()
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="SessionModel not found")
        
        return db_session
    
    def get_session_by_id(self, session_id: UUID) -> SessionModel:
        db_session = self.db_sync.query(SessionModel).filter(SessionModel.id == session_id).first()
        if db_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return db_session
    
    def get_current_single_session(self, user_id: UUID) -> SessionModel | None:
        db_session = (
            self.db_sync.query(SessionModel)
            .filter(
                SessionModel.users.any(id=user_id),
                SessionModel.is_group.is_(False),
                SessionModel.is_active.is_(True)
            )
            .order_by(SessionModel.start_time.desc())  # Order by start_time descending
            .first()
        )
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return db_session
    
    async def get_current_single_session_async(self, user_id: UUID) -> SessionModel | None:
        stmt = (
            select(SessionModel)
            .join(SessionModel.users)
            .filter(
                User.id == user_id,
                SessionModel.is_group.is_(False),
                SessionModel.is_active.is_(True)
            )
            .order_by(desc(SessionModel.start_time))
        )
        
        result = await self.db_async.execute(stmt)
        db_session = result.scalars().first()
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return db_session
    
    def get_current_group_session(self, channel_discord_id: str) -> SessionModel | None:
        db_session = (
            self.db_sync.query(SessionModel)
            .filter(
                SessionModel.channel_discord_id == channel_discord_id,
                SessionModel.is_group.is_(True),
                SessionModel.is_active.is_(True)
            )
            .order_by(SessionModel.start_time.desc())  # Order by start_time descending
            .first()
        )
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return db_session

    async def get_current_group_session_async(self, channel_discord_id: str) -> SessionModel | None:
        stmt = (
            select(SessionModel)
            .filter(
                SessionModel.channel_discord_id == channel_discord_id,
                SessionModel.is_group.is_(True),
                SessionModel.is_active.is_(True)
            )
            .order_by(desc(SessionModel.start_time))
        )
        
        result = await self.db_async.execute(stmt)
        db_session = result.scalars().first()
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return db_session

    def update_session(self, session_id: UUID, session_data: SessionBase) -> SessionModel:
        db_session = self.db_sync.query(SessionModel).filter(SessionModel.id == session_id).first()
        if db_session is None:
            raise HTTPException(status_code=404, detail="SessionModel not found")
        for key, value in session_data.model_dump(exclude_unset=True).items():
            setattr(db_session, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_session)
        return db_session
    
    async def update_session_async(self, session_id: UUID, session_data: SessionBase) -> SessionModel:
        stmt = select(SessionModel).filter(SessionModel.id == session_id)
        result = await self.db_async.execute(stmt)
        db_session = result.scalars().first()
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="SessionModel not found")
        
        for key, value in session_data.model_dump(exclude_unset=True).items():
            setattr(db_session, key, value)
        
        await self.db_async.commit()
        await self.db_async.refresh(db_session)
        
        return db_session

    def delete_session(self, session_id: UUID) -> SessionModel:
        db_session = self.db_sync.query(SessionModel).filter(SessionModel.id == session_id).first()
        if db_session is None:
            raise HTTPException(status_code=404, detail="SessionModel not found")
        self.db_sync.delete(db_session)
        self.db_sync.commit()
        return db_session

    async def delete_session_async(self, session_id: UUID) -> SessionModel:
        stmt = select(SessionModel).filter(SessionModel.id == session_id)
        
        result = await self.db_async.execute(stmt)
        db_session = result.scalars().first()
        
        if db_session is None:
            raise HTTPException(status_code=404, detail="SessionModel not found")
        
        await self.db_async.delete(db_session)
        await self.db_async.commit()
        
        return db_session

    def get_active_single_sessions(self, user_id: UUID) -> list[SessionModel]:
        db_sessions = (
            self.db_sync.query(SessionModel)
            .filter(
                SessionModel.users.any(id=user_id),
                SessionModel.is_group.is_(False),
                SessionModel.is_active.is_(True)
            )
            .all()
        )
        if db_sessions == []:
            raise HTTPException(status_code=404, detail="Single Session not found")
        
        return db_sessions
    
    async def get_active_single_sessions_async(self, user_id: UUID) -> list[SessionModel]:
        stmt = (
            select(SessionModel)
            .join(SessionModel.users)
            .filter(
                User.id == user_id,
                SessionModel.is_group.is_(False),
                SessionModel.is_active.is_(True)
            )
        )
        
        result = await self.db_async.execute(stmt)
        db_sessions = result.scalars().all()
        
        if not db_sessions:
            raise HTTPException(status_code=404, detail="Single Session not found")
        
        return db_sessions

    def get_active_group_sessions(self, channel_discord_id: str) -> list[SessionModel]:
        db_sessions = (
            self.db_sync.query(SessionModel)
            .filter(
                SessionModel.channel_discord_id == channel_discord_id,
                SessionModel.is_group.is_(True),
                SessionModel.is_active.is_(True)
            )
            .all()
        )
        if db_sessions == []:
            raise HTTPException(status_code=404, detail="Group Session not found")
        
        return db_sessions
    
    async def get_active_group_sessions_async(self, channel_discord_id: str) -> list[SessionModel]:
        stmt = (
            select(SessionModel)
            .filter(
                SessionModel.channel_discord_id == channel_discord_id,
                SessionModel.is_group.is_(True),
                SessionModel.is_active.is_(True)
            )
        )
        
        result = await self.db_async.execute(stmt)
        db_sessions = result.scalars().all()
        
        if not db_sessions:
            raise HTTPException(status_code=404, detail="Group Session not found")
        
        return db_sessions


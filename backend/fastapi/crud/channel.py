from typing import List, Optional
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy.sql import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.fastapi.dependencies.database import get_sync_db, get_async_db
from backend.fastapi.models import Channel, User
from backend.fastapi.schemas import ChannelUpdate, ChannelCreate

class ChannelService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async
    
    def create_channel(self, channel_data: ChannelCreate) -> Channel:
        channel_dict = channel_data.model_dump()
        
        # Fetch the User instances
        if channel_data.users:
            user_ids = channel_data.users
            users = self.db_sync.query(User).filter(User.id.in_(user_ids)).all()
            if len(users) != len(user_ids):
                raise HTTPException(status_code=404, detail="One or more users not found")
            channel_dict['users'] = users
        else:
            channel_dict['users'] = []

        db_channel = Channel(**channel_dict)
        self.db_sync.add(db_channel)
        self.db_sync.commit()
        self.db_sync.refresh(db_channel)
        return db_channel
    
    async def create_channel_async(self, channel_data: ChannelCreate) -> Channel:
        db_channel = Channel(**channel_data.model_dump())
        self.db_async.add(db_channel)
        await self.db_async.commit()
        await self.db_async.refresh(db_channel)
        return db_channel

    def get_channels(self, skip: int = 0, limit: int = 30) -> List[Channel]:
        return self.db_sync.query(Channel).offset(skip).limit(limit).all()

    def get_channel_by_channel_discord_id(self, channel_discord_id: str) -> Channel:
        db_channel = self.db_sync.query(Channel).filter(Channel.channel_discord_id == channel_discord_id).first()
        if db_channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        return db_channel

    def get_channel_by_channel_discord_id_and_group_status(self, channel_discord_id: str, is_group: bool, user_id: Optional[UUID] = None) -> Channel:
        query = (
            self.db_sync.query(Channel)
            .filter(Channel.channel_discord_id == channel_discord_id, Channel.is_group == is_group)
        )
        if not is_group and user_id:
            query = query.filter(Channel.user_id == user_id)
        
        db_channel = query.first()
        if db_channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        return db_channel    

    def update_channel(self, channel_id: UUID, channel_data: ChannelUpdate) -> Channel:
        db_channel = self.db_sync.query(Channel).filter(Channel.id == channel_id).first()
        if db_channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        for key, value in channel_data.model_dump(exclude_unset=True).items():
            setattr(db_channel, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_channel)
        return db_channel

    def delete_channel(self, channel_id: UUID) -> Channel:
        db_channel = self.db_sync.query(Channel).filter(Channel.id == channel_id).first()
        if db_channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        self.db_sync.delete(db_channel)
        self.db_sync.commit()
        return db_channel
    
    async def delete_channel_async(self, channel_id: UUID) -> Channel:
        # Construct a select statement to find the channel by ID
        stmt = select(Channel).filter(Channel.id == channel_id)
        result = await self.db_async.execute(stmt)
        db_channel = result.scalars().first()

        # Check if the channel exists
        if db_channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Perform the deletion
        await self.db_async.delete(db_channel)
        await self.db_async.commit()
        return db_channel

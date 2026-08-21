from typing import List
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.fastapi.dependencies.database import get_sync_db, get_async_db
from backend.fastapi.models import Server, User
from backend.fastapi.schemas import ServerBase, ServerCreate

class ServerService:
    def __init__(self, db_sync: Session = Depends(get_sync_db), db_async: AsyncSession = Depends(get_async_db)):
        self.db_sync = db_sync
        self.db_async = db_async
    
    def create_server(self, server_data: ServerCreate) -> Server:
        server_dict = server_data.model_dump()
        
        # Fetch the User instances
        if server_data.users:
            user_ids = server_data.users
            users = self.db_sync.query(User).filter(User.id.in_(user_ids)).all()
            if len(users) != len(user_ids):
                raise HTTPException(status_code=404, detail="One or more users not found")
            server_dict['users'] = users
        else:
            server_dict['users'] = []

        db_server = Server(**server_dict)
        self.db_sync.add(db_server)
        self.db_sync.commit()
        self.db_sync.refresh(db_server)
        return db_server
    
    async def create_server_async(self, server_data: ServerCreate) -> Server:
        db_server = Server(**server_data.model_dump())
        self.db_async.add(db_server)
        await self.db_async.commit()
        await self.db_async.refresh(db_server)
        return db_server

    def get_servers(self, skip: int = 0, limit: int = 30) -> List[Server]:
        return self.db_sync.query(Server).offset(skip).limit(limit).all()

    def get_server_by_server_discord_id(self, server_discord_id: str) -> Server:
        db_server = self.db_sync.query(Server).filter(Server.server_discord_id == server_discord_id).first()
        if db_server is None:
            raise HTTPException(status_code=404, detail="Server not found")
        return db_server

    def update_server(self, server_id: UUID, server_data: ServerBase) -> Server:
        db_server = self.db_sync.query(Server).filter(Server.id == server_id).first()
        if db_server is None:
            raise HTTPException(status_code=404, detail="Server not found")
        for key, value in server_data.model_dump(exclude_unset=True).items():
            setattr(db_server, key, value)
        self.db_sync.commit()
        self.db_sync.refresh(db_server)
        return db_server

    def delete_server(self, server_id: UUID) -> Server:
        db_server = self.db_sync.query(Server).filter(Server.id == server_id).first()
        if db_server is None:
            raise HTTPException(status_code=404, detail="Server not found")
        self.db_sync.delete(db_server)
        self.db_sync.commit()
        return db_server
    
    async def delete_server_async(self, server_id: UUID) -> Server:
        stmt = select(Server).filter(Server.id == server_id)
        result = await self.db_async.execute(stmt)
        db_server = result.scalars().first()

        if db_server is None:
            raise HTTPException(status_code=404, detail="Server not found")

        await self.db_async.delete(db_server)
        await self.db_async.commit()
        return db_server

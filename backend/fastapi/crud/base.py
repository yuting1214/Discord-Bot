"""Shared async CRUD behaviour.

The services used to carry a synchronous and an asynchronous copy of every
method, backed by two engines and two drivers. Nothing calls the synchronous
half any more -- the bot talks to backend/discord/service.py directly -- and a
blocking driver inside an async application is the wrong thing for a template to
demonstrate, so only the async path remains.
"""

from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.fastapi.dependencies.database import get_async_db


class AsyncCRUD[ModelType]:
    """Create/read/update/delete for one model, over an async session."""

    model: type
    not_found_detail: str = "Not found"

    def __init__(self, db: AsyncSession = Depends(get_async_db)):
        self.db = db

    async def create(self, data) -> ModelType:
        instance = self.model(**data.model_dump())
        self.db.add(instance)
        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    async def list(self, skip: int = 0, limit: int = 30) -> list[ModelType]:
        result = await self.db.execute(select(self.model).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def get(self, item_id: UUID) -> ModelType:
        instance = (
            await self.db.execute(select(self.model).where(self.model.id == item_id))
        ).scalars().first()
        if instance is None:
            raise HTTPException(status_code=404, detail=self.not_found_detail)
        return instance

    async def update(self, item_id: UUID, data) -> ModelType:
        instance = await self.get(item_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(instance, key, value)
        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    async def delete(self, item_id: UUID) -> ModelType:
        instance = await self.get(item_id)
        # Delete by statement rather than session.delete(): the latter cascades
        # through relationships, which needs them eagerly loaded first.
        await self.db.execute(sql_delete(self.model).where(self.model.id == item_id))
        await self.db.commit()
        return instance

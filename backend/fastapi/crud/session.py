from uuid import UUID

from sqlalchemy import desc, select

from backend.fastapi.crud.base import AsyncCRUD
from backend.fastapi.models import Session as SessionModel
from backend.fastapi.models import User
from backend.fastapi.schemas import SessionCreate


class SessionService(AsyncCRUD[SessionModel]):
    model = SessionModel
    not_found_detail = "Session not found"

    async def create(self, data: SessionCreate) -> SessionModel:
        """Override: `users` arrives as a list of ids and must become instances."""
        payload = data.model_dump()
        user_ids = payload.pop("users", []) or []
        users = []
        if user_ids:
            users = list(
                (await self.db.execute(select(User).where(User.id.in_(user_ids))))
                .scalars()
                .all()
            )
        instance = SessionModel(**payload, users=users)
        self.db.add(instance)
        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    async def _active(self, is_group: bool, channel_discord_id=None, user_id=None):
        stmt = select(SessionModel).where(
            SessionModel.is_active.is_(True), SessionModel.is_group.is_(is_group)
        )
        if is_group:
            stmt = stmt.where(SessionModel.channel_discord_id == channel_discord_id)
        else:
            stmt = stmt.join(SessionModel.users).where(User.id == user_id)
        result = await self.db.execute(stmt.order_by(desc(SessionModel.start_time)))
        return list(result.scalars().all())

    async def get_active_single(self, user_id: UUID) -> list[SessionModel]:
        return await self._active(is_group=False, user_id=user_id)

    async def get_active_group(self, channel_discord_id: str) -> list[SessionModel]:
        return await self._active(is_group=True, channel_discord_id=channel_discord_id)

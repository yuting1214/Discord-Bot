from uuid import UUID

from sqlalchemy import select

from backend.fastapi.crud.base import AsyncCRUD
from backend.fastapi.models import Channel


class ChannelService(AsyncCRUD[Channel]):
    model = Channel
    not_found_detail = "Channel not found"

    async def get_by_channel_discord_id(
        self, channel_discord_id: str, is_group: bool, user_id: UUID | None = None
    ) -> Channel | None:
        stmt = select(Channel).where(
            Channel.channel_discord_id == channel_discord_id,
            Channel.is_group.is_(is_group),
        )
        if not is_group and user_id:
            stmt = stmt.where(Channel.user_id == user_id)
        return (await self.db.execute(stmt)).scalars().first()

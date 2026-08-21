from sqlalchemy import select

from src.backend.fastapi.crud.base import AsyncCRUD
from src.backend.fastapi.models import Server


class ServerService(AsyncCRUD[Server]):
    model = Server
    not_found_detail = "Server not found"

    async def get_by_server_discord_id(self, server_discord_id: str) -> Server | None:
        return (
            await self.db.execute(
                select(Server).where(Server.server_discord_id == server_discord_id)
            )
        ).scalars().first()

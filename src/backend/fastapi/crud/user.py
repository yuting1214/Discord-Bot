from sqlalchemy import select

from src.backend.fastapi.crud.base import AsyncCRUD
from src.backend.fastapi.models import User


class UserService(AsyncCRUD[User]):
    model = User
    not_found_detail = "User not found"

    async def get_by_discord_id(self, discord_id: str) -> User | None:
        return (
            await self.db.execute(select(User).where(User.discord_id == discord_id))
        ).scalars().first()

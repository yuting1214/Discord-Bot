from sqlalchemy import select

from src.backend.fastapi.crud.base import AsyncCRUD
from src.backend.fastapi.models import Command
from src.backend.fastapi.schemas import CommandCreate


class CommandService(AsyncCRUD[Command]):
    model = Command
    not_found_detail = "Command not found"

    async def get_by_name(self, name: str) -> Command | None:
        return (
            await self.db.execute(select(Command).where(Command.name == name))
        ).scalars().first()


async def create_init_command_async(db, command: dict) -> Command | None:
    """Seed one command row, skipping it if the name is already present."""
    existing = (
        await db.execute(select(Command).where(Command.name == command["name"]))
    ).scalars().first()
    if existing is not None:
        return existing

    instance = Command(**CommandCreate(**command).model_dump())
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return instance

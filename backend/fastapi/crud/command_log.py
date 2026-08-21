from backend.fastapi.crud.base import AsyncCRUD
from backend.fastapi.models import CommandLog


class CommandLogService(AsyncCRUD[CommandLog]):
    model = CommandLog
    not_found_detail = "Command log not found"

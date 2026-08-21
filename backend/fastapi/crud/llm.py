from backend.fastapi.crud.base import AsyncCRUD
from backend.fastapi.models import LLM


class LLMService(AsyncCRUD[LLM]):
    model = LLM
    not_found_detail = "LLM not found"

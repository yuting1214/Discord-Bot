from src.backend.fastapi.crud.base import AsyncCRUD
from src.backend.fastapi.models import LLMUsage


class LLMUsageService(AsyncCRUD[LLMUsage]):
    model = LLMUsage
    not_found_detail = "LLM usage not found"

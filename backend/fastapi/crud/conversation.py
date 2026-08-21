from backend.fastapi.crud.base import AsyncCRUD
from backend.fastapi.models import Conversation


class ConversationService(AsyncCRUD[Conversation]):
    model = Conversation
    not_found_detail = "Conversation not found"

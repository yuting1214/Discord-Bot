from uuid import UUID

from sqlalchemy import asc, case, desc, select

from src.backend.constants import MEMORY_WINDOW_SIZE
from src.backend.fastapi.crud.base import AsyncCRUD
from src.backend.fastapi.models import Conversation, Message


def _conversation_order(conversation_ids: list[UUID]):
    """ORDER BY that preserves the given conversation_id sequence."""
    return case(
        *((Message.conversation_id == cid, index) for index, cid in enumerate(conversation_ids)),
        else_=len(conversation_ids),
    )


class MessageService(AsyncCRUD[Message]):
    model = Message
    not_found_detail = "Message not found"

    async def get_latest(
        self, session_id: UUID, n: int = MEMORY_WINDOW_SIZE
    ) -> list[Message]:
        conversations = (
            await self.db.execute(
                select(Conversation)
                .where(Conversation.session_id == session_id)
                .order_by(desc(Conversation.start_time))
                .limit(n)
            )
        ).scalars().all()
        conversation_ids = [c.id for c in conversations]
        if not conversation_ids:
            return []

        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(_conversation_order(conversation_ids), desc(Message.timestamp))
        )
        return list(result.scalars().all())

    async def get_by_conversations(self, conversation_ids: list[UUID]) -> list[Message]:
        if not conversation_ids:
            return []
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(_conversation_order(conversation_ids), asc(Message.timestamp))
        )
        return list(result.scalars().all())

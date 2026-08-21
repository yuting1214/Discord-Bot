"""Database operations for the Discord bot, executed directly against the session.

This replaces the previous ``operations/`` package, in which the bot reached its
own FastAPI app over HTTP -- out through ``RAILWAY_PUBLIC_DOMAIN`` and back into
the same container -- for every read and write. A single slash command cost six
to ten public-internet round trips, billed as egress, and failed outright during
cold start before the domain had TLS.

It also retires ``rollback_manager``, which attempted to undo partial work by
issuing compensating DELETE and POST requests. Those compensations could
themselves fail, leaving the database inconsistent with no record. Callers now
wrap their work in a real transaction instead.
"""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import asc, case, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.constants import CURRENT_TIMEZONE, MEMORY_WINDOW_SIZE
from backend.discord.utils import generate_uuid_key
from backend.fastapi.models import (
    LLM,
    Channel,
    Command,
    CommandLog,
    Conversation,
    LLMUsage,
    Message,
    Server,
    Session,
    User,
)

logger = logging.getLogger(__name__)


async def get_or_create_user(db: AsyncSession, discord_id: str, username: str) -> User:
    user = (await db.execute(select(User).where(User.discord_id == discord_id))).scalars().first()
    if user is None:
        user = User(discord_id=discord_id, username=username)
        db.add(user)
        await db.flush()
    return user


async def get_or_create_server(
    db: AsyncSession, server_discord_id: str, server_name: str, owner_discord_id: str, user: User
) -> Server:
    server = (
        await db.execute(
            select(Server)
            .options(selectinload(Server.users))
            .where(Server.server_discord_id == server_discord_id)
        )
    ).scalars().first()
    if server is None:
        server = Server(
            server_discord_id=server_discord_id,
            server_name=server_name,
            owner_discord_id=owner_discord_id,
            users=[user],
        )
        db.add(server)
        await db.flush()
    elif user not in server.users:
        server.users.append(user)
    return server


async def get_or_create_channel(
    db: AsyncSession,
    server_id: UUID,
    channel_discord_id: str,
    channel_name: str,
    user: User,
    is_group: bool,
) -> Channel:
    stmt = (
        select(Channel)
        .options(selectinload(Channel.users))
        .where(Channel.channel_discord_id == channel_discord_id, Channel.is_group == is_group)
    )
    if not is_group:
        stmt = stmt.where(Channel.user_id == user.id)

    channel = (await db.execute(stmt)).scalars().first()
    if channel is not None:
        return channel

    channel = Channel(
        server_id=server_id,
        channel_discord_id=channel_discord_id,
        channel_name=channel_name,
        is_group=is_group,
        users=[user] if is_group else [],
        user_id=None if is_group else user.id,
    )
    db.add(channel)
    await db.flush()
    return channel


def search_index_key(user_id: UUID, channel_id: UUID, is_group: bool) -> str:
    """Scope searches to a group channel, or to one user within a channel.

    Single sessions are keyed per (user, channel) so one user's history is never
    searchable from another's.
    """
    return str(channel_id) if is_group else generate_uuid_key(user_id, channel_id)


async def find_active_sessions(
    db: AsyncSession, channel_discord_id: str, user_id: UUID, is_group: bool
) -> list[Session]:
    stmt = select(Session).where(Session.is_active.is_(True), Session.is_group.is_(is_group))
    if is_group:
        stmt = stmt.where(Session.channel_discord_id == channel_discord_id)
    else:
        stmt = stmt.join(Session.users).where(User.id == user_id)
    return list((await db.execute(stmt.order_by(desc(Session.start_time)))).scalars().all())


def deactivate_session(session: Session) -> None:
    session.is_active = False
    session.end_time = datetime.now(CURRENT_TIMEZONE).replace(tzinfo=None)


def activate_session(session: Session) -> None:
    session.is_active = True
    session.end_time = None


async def get_session_if_exists(db: AsyncSession, session_id: UUID | str) -> Session | None:
    """Look up a session by id.

    Accepts a string because it is fed by ``extract_uuid`` on user input; the
    column is typed UUID and will not compare against a str.
    """
    if isinstance(session_id, str):
        try:
            session_id = UUID(session_id)
        except ValueError:
            return None
    return (await db.execute(select(Session).where(Session.id == session_id))).scalars().first()


async def manage_session(
    db: AsyncSession, channel_discord_id: str, user: User, is_group: bool, is_new_session: bool
) -> Session:
    """Return the session this command should write to.

    A new session deactivates whatever was active; an ongoing one is reused, or
    created if nothing is active yet.
    """
    active = await find_active_sessions(db, channel_discord_id, user.id, is_group)

    if not is_new_session and active:
        return active[0]

    for session in active:
        deactivate_session(session)

    session = Session(
        channel_discord_id=channel_discord_id, is_active=True, is_group=is_group, users=[user]
    )
    db.add(session)
    await db.flush()
    return session


async def create_conversation(db: AsyncSession, session_id: UUID) -> Conversation:
    conversation = Conversation(session_id=session_id)
    db.add(conversation)
    await db.flush()
    return conversation


async def end_conversation(db: AsyncSession, conversation_id: UUID) -> None:
    conversation = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalars().first()
    if conversation is not None:
        conversation.end_time = datetime.now(CURRENT_TIMEZONE).replace(tzinfo=None)


async def create_message(
    db: AsyncSession,
    *,
    channel_discord_id: str,
    session_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
    message_type: str,
    content: str,
    reasoning_details: list | None = None,
) -> Message:
    message = Message(
        channel_discord_id=channel_discord_id,
        session_id=session_id,
        conversation_id=conversation_id,
        user_id=user_id,
        message_type=message_type,
        content=content,
        reasoning_details=reasoning_details,
    )
    db.add(message)
    await db.flush()
    return message


async def create_command_log(
    db: AsyncSession, user_id: UUID, session_id: UUID, is_group: bool, is_new_session: bool
) -> CommandLog | None:
    command_name = (
        "start_group_session" if is_group and is_new_session else
        "bot_group" if is_group else
        "start_session" if is_new_session else
        "bot"
    )
    command = (
        await db.execute(select(Command).where(Command.name == command_name))
    ).scalars().first()
    if command is None:
        # Command seeding failed or the name drifted; the chat itself is more
        # important than its audit row.
        logger.warning("No command row named %r; skipping command log", command_name)
        return None

    command_log = CommandLog(user_id=user_id, session_id=session_id, command_id=command.id)
    db.add(command_log)
    await db.flush()
    return command_log


async def record_llm_usage(
    db: AsyncSession, session_id: UUID, model: str, input_tokens: int, output_tokens: int
) -> LLMUsage | None:
    """Record token usage, best effort.

    Requires a matching row in ``llms``; usage is skipped rather than failing the
    user's message when the model in use has not been seeded.
    """
    llm = (await db.execute(select(LLM).where(LLM.api_endpoint == model))).scalars().first()
    if llm is None:
        logger.debug("No llms row for api_endpoint %r; skipping usage record", model)
        return None

    usage = LLMUsage(
        llm_id=llm.id,
        session_id=session_id,
        timestamp=datetime.now(CURRENT_TIMEZONE).replace(tzinfo=None),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(usage)
    await db.flush()
    return usage


def _conversation_order(conversation_ids: list[UUID]):
    """ORDER BY that preserves the given conversation_id sequence."""
    return case(
        *((Message.conversation_id == cid, index) for index, cid in enumerate(conversation_ids)),
        else_=len(conversation_ids),
    )


async def get_latest_messages(
    db: AsyncSession, session_id: UUID, n: int = MEMORY_WINDOW_SIZE
) -> list[dict]:
    """Return the last ``n`` conversations' messages, newest conversation first.

    Shaped as dicts for ``format_memory``, which is what the LLM layer consumes.
    """
    conversations = (
        await db.execute(
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(desc(Conversation.start_time))
            .limit(n)
        )
    ).scalars().all()
    conversation_ids = [c.id for c in conversations]
    if not conversation_ids:
        return []

    messages = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(_conversation_order(conversation_ids), desc(Message.timestamp))
        )
    ).scalars().all()

    return [
        {
            "message_type": m.message_type,
            "content": m.content,
            "reasoning_details": m.reasoning_details,
        }
        for m in messages
    ]


async def get_messages_by_conversations(
    db: AsyncSession, conversation_ids: list[UUID | str]
) -> list[dict]:
    # Ids arrive from the search index as strings; the column is typed UUID.
    conversation_ids = [
        UUID(cid) if isinstance(cid, str) else cid for cid in conversation_ids
    ]
    if not conversation_ids:
        return []
    messages = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(_conversation_order(conversation_ids), asc(Message.timestamp))
        )
    ).scalars().all()
    return [
        {
            "session_id": str(m.session_id),
            "message_type": m.message_type,
            "content": m.content,
        }
        for m in messages
    ]

"""Session summarisation: one embedding per session instead of one per turn.

Every user message used to be embedded as it arrived -- O(turns) provider calls,
on the hot path of every command. Most turns do not deserve one. "you good?" is
a real message from production that embedded to something plausible and
outranked a genuinely relevant turn, because a short conversational aside sits
near everything in vector space.

A session summary is O(sessions), roughly a 10-20x reduction, and it is dense
and topical rather than conversational, so the failure above disappears by
construction rather than by tuning.

Lexical search is unaffected and still covers every individual message: BM25 is
populated by a database trigger with no API call, so "find where I said X"
remains exact and works on sessions that are still open.

Three things start a summarisation, because each one leaves a hole the others do
not cover:

  1. the session being deactivated -- the common case
  2. the idle sweep -- a session nobody ever closes is otherwise never summarised
  3. POST /api/v1/sessions/{id}/summary -- backfill, and a way to retry a failure
"""

import asyncio
import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.constants import utcnow
from src.backend.fastapi.dependencies.database import AsyncSessionLocal
from src.backend.fastapi.models import Message, Session
from src.backend.search.embeddings import embed
from src.config import bot_config
from src.llm.chat import achat

logger = logging.getLogger(__name__)

# A summary of nothing is not worth a provider call.
MIN_MESSAGES = 2
# Enough to characterise a session without paying for a whole long one. The
# oldest turns set the topic; the newest say where it ended up.
MAX_CHARS = 6000


def _transcript(messages: list[Message]) -> str:
    lines = [f"{'User' if m.message_type == 'user' else 'Assistant'}: {m.content}" for m in messages]
    body = "\n".join(lines)
    if len(body) <= MAX_CHARS:
        return body
    half = MAX_CHARS // 2
    return f"{body[:half]}\n...\n{body[-half:]}"


async def _load_messages(db: AsyncSession, session_id: UUID) -> list[Message]:
    return list((await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.timestamp)
    )).scalars().all())


async def summarize_session(db: AsyncSession, session_id: UUID, *, force: bool = False) -> str | None:
    """Summarise one session and store the summary with its embedding.

    Returns the summary, or None when there was nothing worth summarising.
    Already-summarised sessions are skipped unless ``force``, so the sweep and a
    deactivation racing each other cost one call rather than two.
    """
    session = await db.get(Session, session_id)
    if session is None:
        logger.warning("Cannot summarise unknown session %s", session_id)
        return None
    if session.summarized_at is not None and not force:
        return session.summary

    messages = await _load_messages(db, session_id)
    if len(messages) < MIN_MESSAGES:
        # Marked as done anyway: an empty session must not be retried by every
        # sweep for the rest of its life.
        session.summarized_at = utcnow()
        return None

    result = await achat(_transcript(messages), memory=None, system_prompt=bot_config.prompts.summary)
    summary = (result.text or "").strip()
    if not summary:
        logger.warning("Empty summary for session %s; leaving it for the next sweep", session_id)
        return None

    session.summary = summary
    session.summary_vector = await embed(summary)
    session.summarized_at = utcnow()
    logger.info("Summarised session %s (%d messages)", session_id, len(messages))
    return summary


async def summarize_session_in_background(session_id: UUID) -> None:
    """Summarise in its own database session, swallowing every failure.

    Called from a fire-and-forget task after the caller's transaction has
    committed. A provider outage must not fail the command the user actually
    ran, and it must not surface as an unhandled task exception; the sweep will
    pick the session up again because summarized_at stays NULL.
    """
    if not bot_config.summary.enabled:
        return
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                await summarize_session(db, session_id)
    except Exception:
        logger.warning("Background summarisation failed for %s", session_id, exc_info=True)


async def summarize_idle_sessions(db: AsyncSession, *, now=None) -> int:
    """Summarise sessions that have gone quiet but were never deactivated.

    Without this, a session a user simply walks away from stays active forever
    and never becomes semantically searchable.
    """
    settings = bot_config.summary
    cutoff = (now or utcnow()) - timedelta(minutes=settings.idle_minutes)

    # Ordered oldest-first so a backlog drains in a predictable order rather
    # than the same batch being retried.
    stale = (await db.execute(
        select(Session.id)
        .where(Session.summarized_at.is_(None), Session.start_time < cutoff)
        .order_by(Session.start_time)
        .limit(settings.batch_size)
    )).scalars().all()

    summarised = 0
    for session_id in stale:
        try:
            if await summarize_session(db, session_id):
                summarised += 1
        except Exception:
            # One bad session must not stop the batch.
            logger.warning("Could not summarise %s during sweep", session_id, exc_info=True)
    return summarised


# Fire-and-forget tasks are garbage collected if nothing holds a reference, and
# a collected task is silently cancelled mid-request.
_pending: set = set()


def schedule_summary(session_id: UUID) -> None:
    """Summarise after the caller's transaction commits, off the hot path.

    A summary costs a completion and an embedding. Doing that inline would add
    seconds to the command that happened to close the session, for a result the
    user did not ask for.
    """
    if not bot_config.summary.enabled:
        return

    task = asyncio.create_task(summarize_session_in_background(session_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)

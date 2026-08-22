from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.fastapi.crud import SessionService
from src.backend.fastapi.dependencies.database import get_async_db
from src.backend.fastapi.models import Session
from src.backend.fastapi.schemas import (
    SessionCreate,
    SessionSchema,
    SessionSummary,
    SessionUpdate,
)
from src.backend.search.summary import summarize_session
from src.backend.security.authentication import require_admin_session

router = APIRouter()


@router.post("/sessions/", response_model=SessionSchema)
async def create_session(session_data: SessionCreate, service: SessionService = Depends()):
    return await service.create(session_data)


@router.get("/sessions/", response_model=list[SessionSchema])
async def list_sessions(skip: int = 0, limit: int = 30, service: SessionService = Depends()):
    return await service.list(skip, limit)


@router.get("/sessions/{session_id}", response_model=SessionSchema)
async def get_session(session_id: UUID, service: SessionService = Depends()):
    return await service.get(session_id)


@router.put("/sessions/{session_id}", response_model=SessionSchema)
async def update_session(session_id: UUID, session_data: SessionUpdate, service: SessionService = Depends()):
    return await service.update(session_id, session_data)


@router.delete("/sessions/{session_id}", response_model=SessionSchema)
async def delete_session(session_id: UUID, service: SessionService = Depends()):
    return await service.delete(session_id)


@router.get("/sessions/active/single/", response_model=list[SessionSchema])
async def get_active_single_sessions(user_id: UUID, service: SessionService = Depends()):
    return await service.get_active_single(user_id)


@router.get("/sessions/active/group/", response_model=list[SessionSchema])
async def get_active_group_sessions(channel_discord_id: str, service: SessionService = Depends()):
    return await service.get_active_group(channel_discord_id)


@router.post(
    "/sessions/{session_id}/summary",
    response_model=SessionSummary,
    dependencies=[Depends(require_admin_session)],
)
async def create_session_summary(
    session_id: UUID,
    force: bool = False,
    db: AsyncSession = Depends(get_async_db),
):
    """Summarise a session now, and embed the summary.

    The other two paths -- closing a session, and the idle sweep -- cover normal
    operation. This one exists for backfilling sessions that predate
    summarisation, and for retrying one whose provider call failed.

    Already-summarised sessions are returned unchanged unless ``force``, so this
    is safe to call in a loop over every session id.

    Behind the /docs login, unlike the rest of this API. It calls a paid
    provider on demand, and ``force`` removes the once-per-session guard -- open
    to the internet that is an unbounded charge against whoever deployed this.
    """
    summary = await summarize_session(db, session_id, force=force)
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id}")
    await db.commit()
    return SessionSummary(
        session_id=session_id, summary=summary, summarized=session.summarized_at is not None
    )

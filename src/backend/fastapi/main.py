import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.backend.data.discord_command import command_data
from src.backend.discord.register import build_client, run_discord_bot
from src.backend.fastapi.api.v1.endpoints import (
    channel,
    command,
    command_log,
    conversation,
    doc,
    message,
    server,
    session,
    user,
)
from src.backend.fastapi.core.init_settings import global_settings as settings
from src.backend.fastapi.crud.command import create_init_command_async
from src.backend.fastapi.dependencies.database import AsyncSessionLocal, async_engine, init_db
from src.backend.search.summary import summarize_idle_sessions
from src.backend.security.authentication import log_credentials_once
from src.config import bot_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )

    # Initialize the database connection
    await init_db()

    # Surface generated docs credentials before anything can need them.
    log_credentials_once()

    async with AsyncSessionLocal() as db:
        try:
            for command in command_data:
                await create_init_command_async(db, command)
        finally:
            await db.close()

    # The bot shares this event loop with the web application on purpose. Giving
    # it a loop of its own (a thread running client.run()) means both halves use
    # the same SQLAlchemy engine from two loops, and a pooled connection created
    # on one fails on the other with "got Future attached to a different loop".
    client = build_client()
    bot_task = asyncio.create_task(run_discord_bot(client), name="discord-bot")
    bot_task.add_done_callback(_report_bot_exit)

    sweep_task = None
    if bot_config.summary.enabled:
        sweep_task = asyncio.create_task(_summary_sweep(), name="summary-sweep")

    try:
        yield
    finally:
        if not client.is_closed():
            await client.close()
        for task in (bot_task, sweep_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await async_engine.dispose()


async def _summary_sweep() -> None:
    """Summarise sessions that went quiet without ever being closed.

    A user who simply stops replying leaves a session active forever, and a
    session that is never deactivated is never summarised by the other two
    paths -- so it never becomes semantically searchable.

    Every failure is swallowed and retried next interval: this runs for the life
    of the process, and an exception here would silently end it.
    """
    interval = max(bot_config.summary.sweep_interval_minutes, 1) * 60
    log = logging.getLogger(__name__)
    while True:
        try:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    summarised = await summarize_idle_sessions(db)
            if summarised:
                log.info("Summary sweep: summarised %d idle session(s)", summarised)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Summary sweep failed; retrying next interval", exc_info=True)


def _report_bot_exit(task: asyncio.Task) -> None:
    """Surface a bot that died instead of letting it fail silently."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logging.getLogger(__name__).critical(
            "Discord client stopped: %s", error, exc_info=error
        )

# Initialize the FastAPI app
app = FastAPI(lifespan=lifespan)

# Frontend
templates = Jinja2Templates(directory="src/frontend/login/templates")
app.mount("/static", StaticFiles(directory="src/frontend/login/static"), name="static")

# Set Middleware
# Define the allowed origins
origins = [
    os.getenv("API_BASE_URL", ""),
    "http://localhost",
    "http://localhost:5000",
]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Document protection middleware
@app.middleware("http")
async def add_doc_protect(request: Request, call_next):
    if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
        if not request.session.get('authenticated'):
            return RedirectResponse(url="/login")
    response = await call_next(request)
    return response
# Add session middleware with a custom expiration time (e.g., 30 minutes)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY or secrets.token_urlsafe(32),
    max_age=18000,  # 18000 seconds = 300 minutes
)

# Add the routers to the FastAPI app
app.include_router(doc.router, prefix="", tags=["doc"])
modules = [
    server, channel, user, session, conversation, message, command, command_log
]

for module in modules:
    label = module.__name__.lower().split(".")[-1]
    app.include_router(module.router, prefix="/api/v1", tags=[label])


# Uvicorn re-imports the app by name in the worker, so this string must stay in
# step with the package layout. It is asserted in the test suite because a stale
# value only fails at run time, never at import.
APP_IMPORT_STRING = "src.backend.fastapi.main:app"


def fastapi_server_run():
    """Run the whole service: the web application, with the bot inside it."""
    uvicorn.run(
        app=APP_IMPORT_STRING,
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENV_MODE == "dev",  # Enables auto-reloading in development mode
    )


if __name__ == "__main__":
    fastapi_server_run()
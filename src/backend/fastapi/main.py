import logging
import os
import secrets
from contextlib import asynccontextmanager
from threading import Thread

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.backend.data.discord_command import command_data
from src.backend.discord.register import discord_bot_run
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
from src.backend.fastapi.dependencies.database import AsyncSessionLocal, init_db
from src.backend.security.authentication import log_credentials_once


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

    yield

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


def fastapi_server_run():
    # mounting at the root path
    uvicorn.run(
        app="backend.fastapi.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENV_MODE == "dev",  # Enables auto-reloading in development mode
    )

def keep_alive():
    t = Thread(target=fastapi_server_run)
    t.start()

if __name__ == '__main__':
    keep_alive()
    discord_bot_run()
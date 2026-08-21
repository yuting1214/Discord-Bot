import os
from contextlib import asynccontextmanager
from threading import Thread

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from backend.data.discord_command import command_data
from backend.discord.register import discord_bot_run
from backend.fastapi.api.v1.endpoints import (
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
from backend.fastapi.core.init_settings import global_settings as settings
from backend.fastapi.crud.command import create_init_command_async
from backend.fastapi.dependencies.database import AsyncSessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database connection
    init_db()

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
templates = Jinja2Templates(directory="frontend/login/templates")
app.mount("/static", StaticFiles(directory="frontend/login/static"), name="static")

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
app.add_middleware(SessionMiddleware, 
                   secret_key="your_secret_key", 
                   max_age=18000)  # 18000 seconds = 300 minutes

# Add the routers to the FastAPI app
app.include_router(doc.router, prefix="", tags=["doc"])
modules = [
    server, channel, user, session, conversation, message, command, command_log
]

for module in modules:
    label = module.__name__.lower().split(".")[-1]
    app.include_router(module.router_sync, prefix="/api/v1/sync", tags=[label])
    app.include_router(module.router_async, prefix="/api/v1/async", tags=[label])


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
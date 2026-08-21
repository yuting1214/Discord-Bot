import os
import uvicorn
from threading import Thread
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
from backend.fastapi.core.init_settings import args
from backend.fastapi.crud.command import create_init_command_async
from backend.fastapi.api.v1.endpoints import (
    doc,
    server,
    channel,
    session,
    conversation,
    message,
    user,
    command,
    command_log
)
from backend.fastapi.dependencies.database import init_db, AsyncSessionLocal
from backend.data.discord_command import command_data
from backend.discord.register import discord_bot_run
from backend.meilisearch.setup import enable_experimental_features

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database connection
    init_db()

    # Enable Meilisearch experimental metrics
    meilisearch_message = enable_experimental_features()

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
        host = args.host,
        port=int(os.getenv("PORT", 5000)),
        reload=args.mode == "dev"  # Enables auto-reloading in development mode
    )

def keep_alive():
    t = Thread(target=fastapi_server_run)
    t.start()

if __name__ == '__main__':
    keep_alive()
    discord_bot_run()
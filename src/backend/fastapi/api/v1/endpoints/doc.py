from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.fastapi.dependencies.database import get_async_db
from src.backend.security.authentication import authenticate_user

router = APIRouter()
templates = Jinja2Templates(directory="src/frontend/login/templates")

@router.get("/")
def read_root():
    return {"message": "Hello, you're onboard!"}


@router.get("/health")
async def health(db: AsyncSession = Depends(get_async_db)):
    """Liveness probe for the platform healthcheck.

    Reports on the database rather than returning a bare ok, so a container that
    is up but cannot reach PostgreSQL is not counted as healthy.
    """
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    return {"status": "ok" if database == "ok" else "degraded", "database": database}

# Endpoint for login form
@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html")

@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if authenticate_user(username, password):
        request.session['authenticated'] = True
        return RedirectResponse(url="/docs", status_code=303)
    else:
        message = "Invalid credentials"
        return templates.TemplateResponse(request, "login.html", {"message": message})
    
@router.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")
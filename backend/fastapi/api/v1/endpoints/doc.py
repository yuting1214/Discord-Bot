from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.security.authentication import authenticate_user

router = APIRouter()
templates = Jinja2Templates(directory="frontend/login/templates")

@router.get("/")
def read_root():
    return {"message": "Hello, you're onboard!"}

# Endpoint for login form
@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if authenticate_user(username, password):
        request.session['authenticated'] = True
        return RedirectResponse(url="/docs", status_code=303)
    else:
        message = "Invalid credentials"
        return templates.TemplateResponse("login.html", {"request": request, "message": message})
    
@router.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")
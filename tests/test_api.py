"""HTTP-level checks against the app, without starting the Discord client."""

import httpx
import pytest_asyncio

from src.backend.fastapi.dependencies.database import get_async_db
from src.backend.fastapi.main import app
from src.backend.security import authentication


@pytest_asyncio.fixture
async def client(session_factory):
    """An in-process HTTP client on the *test's* event loop.

    Not TestClient. That runs the app on an event loop of its own, and asyncpg
    binds a pooled connection to the loop that created it -- so against
    PostgreSQL every request failed with the connection unavailable, while
    SQLite happily served both loops and hid it.
    """

    async def override():
        async with session_factory() as db:
            yield db

    app.dependency_overrides[get_async_db] = override
    # No lifespan: it would create the real dev database and start the bot.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_health_reports_the_database(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_degrades_when_the_database_is_unreachable():
    """A container that is up but cannot reach PostgreSQL is not healthy."""
    class BrokenSession:
        async def execute(self, *a, **k):
            raise RuntimeError("connection refused")

    async def override():
        yield BrokenSession()

    app.dependency_overrides[get_async_db] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get("/health")
        assert response.status_code == 200, "the probe itself must not error"
        assert response.json() == {"status": "degraded", "database": "unavailable"}
    finally:
        app.dependency_overrides.clear()


async def test_root_is_public(client):
    assert (await client.get("/")).status_code == 200


async def test_docs_require_authentication(client):
    """/docs must redirect to the login form for an unauthenticated session."""
    response = await client.get("/docs", follow_redirects=False)
    assert response.status_code in (302, 307), response.status_code
    assert response.headers["location"] == "/login"


async def test_login_rejects_empty_credentials(client, monkeypatch):
    """The default-deploy configuration: both variables present but empty."""
    authentication.get_credentials.cache_clear()
    monkeypatch.setattr(authentication.settings, "USER_NAME", "")
    monkeypatch.setattr(authentication.settings, "PASSWORD", "")

    # Sent as a raw body: httpx drops empty-string fields, but a browser
    # submits them, which is the case that used to authenticate.
    response = await client.post(
        "/login",
        content="username=&password=",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    # The property that matters is that this does not authenticate. Whether the
    # framework rejects it as invalid (422) or the handler re-renders the form
    # (200) is incidental; a 303 to /docs is the regression.
    assert response.status_code != 303, "empty credentials must not authenticate"
    assert response.headers.get("location") != "/docs"
    authentication.get_credentials.cache_clear()


async def test_login_accepts_configured_credentials(client, monkeypatch):
    authentication.get_credentials.cache_clear()
    monkeypatch.setattr(authentication.settings, "USER_NAME", "alice")
    monkeypatch.setattr(authentication.settings, "PASSWORD", "s3cret-passphrase")

    response = await client.post(
        "/login",
        data={"username": "alice", "password": "s3cret-passphrase"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/docs"
    authentication.get_credentials.cache_clear()


def test_openapi_exposes_the_expected_surface():
    spec = app.openapi()
    paths = set(spec["paths"])
    assert "/health" in paths
    assert {"/", "/login", "/logout"} <= paths
    assert any(p.startswith("/api/v1/") for p in paths)
    # The sync mirror of every endpoint is gone; nothing should remain under it.
    assert not any(p.startswith("/api/v1/sync") for p in paths)


def test_uvicorn_app_import_string_resolves():
    """`uvicorn.run(app="...")` re-imports by name in the worker.

    A stale string here fails only at run time -- it survived the move to src/
    and broke the container, because every other test imports the app object
    directly and never goes through this path.
    """
    from uvicorn.importer import import_from_string

    from src.backend.fastapi.main import APP_IMPORT_STRING
    from src.backend.fastapi.main import app as app_object

    assert import_from_string(APP_IMPORT_STRING) is app_object


def test_prod_without_a_database_says_what_to_set():
    """Assembling a URL from blank parts used to fail deep inside SQLAlchemy with
    "invalid literal for int() with base 10: ''", which names nothing to fix."""
    import pytest

    from src.backend.fastapi.core.config import ProdSettings

    settings = ProdSettings(OPENAI_API_KEY="x", DATABASE_URL="")
    with pytest.raises(RuntimeError) as excinfo:
        _ = settings.ASYNC_DB_URL
    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    assert "DB_HOST" in message


def test_database_url_is_converted_to_asyncpg():
    from src.backend.fastapi.core.config import ProdSettings

    settings = ProdSettings(
        OPENAI_API_KEY="x", DATABASE_URL="postgresql://u:p@host:5432/db"
    )
    assert settings.ASYNC_DB_URL == "postgresql+asyncpg://u:p@host:5432/db"


async def test_login_page_renders(client):
    """The login form must actually render.

    Every earlier test followed /docs -> 302 /login and stopped there, so the
    deprecated TemplateResponse("name", {"request": ...}) signature went
    unnoticed until it 500'd in production: newer Starlette reads the first
    positional as the request, so the template name became a dict and Jinja
    raised "unhashable type: 'dict'".
    """
    response = await client.get("/login")
    assert response.status_code == 200, response.text[:400]
    assert "<form" in response.text.lower()


async def test_docs_redirect_target_is_reachable(client):
    """Follow the redirect all the way, not just to its Location header."""
    response = await client.get("/docs", follow_redirects=True)
    assert response.status_code == 200
    assert "<form" in response.text.lower()


async def test_failed_login_rerenders_the_form_with_a_message(client, monkeypatch):
    authentication.get_credentials.cache_clear()
    monkeypatch.setattr(authentication.settings, "USER_NAME", "alice")
    monkeypatch.setattr(authentication.settings, "PASSWORD", "s3cret-passphrase")
    response = await client.post(
        "/login", data={"username": "alice", "password": "wrong"}, follow_redirects=False
    )
    assert response.status_code == 200, response.text[:300]
    assert "Invalid credentials" in response.text
    authentication.get_credentials.cache_clear()

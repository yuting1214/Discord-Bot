"""HTTP-level checks against the app, without starting the Discord client."""

import pytest
from fastapi.testclient import TestClient

from src.backend.fastapi.dependencies.database import get_async_db
from src.backend.fastapi.main import app
from src.backend.security import authentication


@pytest.fixture
def client(session_factory):
    async def override():
        async with session_factory() as db:
            yield db

    app.dependency_overrides[get_async_db] = override
    # No `with`: the lifespan would create the real dev database and start the bot.
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_reports_the_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_degrades_when_the_database_is_unreachable():
    """A container that is up but cannot reach PostgreSQL is not healthy."""
    class BrokenSession:
        async def execute(self, *a, **k):
            raise RuntimeError("connection refused")

    async def override():
        yield BrokenSession()

    app.dependency_overrides[get_async_db] = override
    try:
        response = TestClient(app).get("/health")
        assert response.status_code == 200, "the probe itself must not error"
        assert response.json() == {"status": "degraded", "database": "unavailable"}
    finally:
        app.dependency_overrides.clear()


def test_root_is_public(client):
    assert client.get("/").status_code == 200


def test_docs_require_authentication(client):
    """/docs must redirect to the login form for an unauthenticated session."""
    response = client.get("/docs", follow_redirects=False)
    assert response.status_code in (302, 307), response.status_code
    assert response.headers["location"] == "/login"


def test_login_rejects_empty_credentials(client, monkeypatch):
    """The default-deploy configuration: both variables present but empty."""
    authentication.get_credentials.cache_clear()
    monkeypatch.setattr(authentication.settings, "USER_NAME", "")
    monkeypatch.setattr(authentication.settings, "PASSWORD", "")

    # Sent as a raw body: httpx drops empty-string fields, but a browser
    # submits them, which is the case that used to authenticate.
    response = client.post(
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


def test_login_accepts_configured_credentials(client, monkeypatch):
    authentication.get_credentials.cache_clear()
    monkeypatch.setattr(authentication.settings, "USER_NAME", "alice")
    monkeypatch.setattr(authentication.settings, "PASSWORD", "s3cret-passphrase")

    response = client.post(
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

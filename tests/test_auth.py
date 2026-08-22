"""Coverage for the credentials guarding /docs and /redoc.

The regression that matters here: the Railway template ships USER_NAME and
PASSWORD as empty strings, and the previous implementation compared the form
against os.getenv() directly -- so "" == "" held and an empty login form
authenticated on a default deploy.
"""

import pytest

from src.backend.security import authentication


@pytest.fixture(autouse=True)
def clear_cache():
    authentication.get_credentials.cache_clear()
    yield
    authentication.get_credentials.cache_clear()


def configure(monkeypatch, username: str, password: str):
    monkeypatch.setattr(authentication.settings, "USER_NAME", username)
    monkeypatch.setattr(authentication.settings, "PASSWORD", password)


def test_empty_credentials_are_rejected(monkeypatch):
    """The exact default-deploy configuration."""
    configure(monkeypatch, "", "")
    assert authentication.authenticate_user("", "") is False


def test_unset_credentials_are_generated_not_blank(monkeypatch):
    configure(monkeypatch, "", "")
    credentials = authentication.get_credentials()
    assert credentials.generated is True
    assert credentials.username and credentials.password
    assert len(credentials.password) >= 24, "generated password must not be guessable"
    # The generated pair is the only thing that works.
    assert authentication.authenticate_user(credentials.username, credentials.password) is True
    assert authentication.authenticate_user("admin", "") is False


def test_generated_password_is_stable_within_a_process(monkeypatch):
    configure(monkeypatch, "", "")
    assert authentication.get_credentials().password == authentication.get_credentials().password


def test_configured_credentials_are_honoured(monkeypatch):
    configure(monkeypatch, "alice", "correct horse battery staple")
    assert authentication.get_credentials().generated is False
    assert authentication.authenticate_user("alice", "correct horse battery staple") is True


@pytest.mark.parametrize(
    "username,password",
    [
        ("alice", "wrong"),
        ("bob", "correct horse battery staple"),
        ("", "correct horse battery staple"),
        ("alice", ""),
        ("ALICE", "correct horse battery staple"),
        ("alice ", "correct horse battery staple"),
    ],
)
def test_bad_credentials_are_rejected(monkeypatch, username, password):
    configure(monkeypatch, "alice", "correct horse battery staple")
    assert authentication.authenticate_user(username, password) is False


def test_partial_credentials_are_only_half_set(monkeypatch):
    """A password without a username still counts as incomplete."""
    configure(monkeypatch, "alice", "")
    credentials = authentication.get_credentials()
    assert credentials.generated is True
    assert credentials.username == "alice"
    assert credentials.password


async def test_the_summary_endpoint_requires_the_docs_login(client):
    """It calls a paid provider on demand, and `force` removes the
    once-per-session guard -- so open to the internet it is an unbounded charge
    against whoever deployed the template. Everything else under /api/v1 is a
    read; this is the one route that spends money."""
    response = await client.post(
        "/api/v1/sessions/00000000-0000-0000-0000-000000000000/summary"
    )
    assert response.status_code == 401, response.text
    assert "/login" in response.json()["detail"]


async def test_the_summary_endpoint_is_reachable_once_signed_in(client, monkeypatch):
    """Gated, not broken."""
    # Patched where it is *used*: doc.py imported the name at module load, so
    # rebinding it on the security module would have no effect here.
    from src.backend.fastapi.api.v1.endpoints import doc

    monkeypatch.setattr(doc, "authenticate_user", lambda u, p: True)
    login = await client.post(
        "/login", data={"username": "admin", "password": "pw"}, follow_redirects=False
    )
    assert login.status_code == 303, login.text

    response = await client.post(
        "/api/v1/sessions/00000000-0000-0000-0000-000000000000/summary"
    )
    assert response.status_code != 401, response.text

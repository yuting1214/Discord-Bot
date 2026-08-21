"""Failures reported to Discord must be actionable but must not leak.

A generic apology tells the operator nothing -- a stale API key looked identical
to a database outage. The full exception cannot be shown either: provider errors
quote the API key and database errors quote the connection string.
"""

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy.exc import OperationalError

from src.backend.discord.errors import GENERIC, describe

# The shape of a real provider rejection, including the partially masked key.
LEAKY = (
    "Error code: 401 - {'error': {'message': 'Incorrect API key provided: "
    "sk-33wy4***************************************HWsp.'}}"
)


def _api_error(cls, status: int, message: str = LEAKY):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return cls(message=message, response=response, body=None)


@pytest.mark.parametrize(
    "error,expected",
    [
        (_api_error(AuthenticationError, 401), "OPENAI_API_KEY"),
        (_api_error(PermissionDeniedError, 403), "not permitted"),
        (_api_error(RateLimitError, 429), "rate-limiting"),
        (_api_error(NotFoundError, 404), "OPENAI_MODEL"),
        (_api_error(BadRequestError, 400), "LLM_TEMPERATURE"),
        (RuntimeError("OPENROUTER_API_KEY is not set, which is required"), "OPENROUTER_API_KEY"),
    ],
)
def test_each_failure_names_what_to_check(error, expected):
    hint = describe(error)
    assert expected in hint
    assert hint != GENERIC


def test_the_api_key_is_never_echoed():
    """The regression that matters: the provider's message contains the key."""
    hint = describe(_api_error(AuthenticationError, 401))
    assert "sk-" not in hint
    assert "HWsp" not in hint
    assert LEAKY not in hint


def test_database_failures_do_not_echo_the_connection_string():
    error = OperationalError(
        "SELECT 1", {}, Exception("could not connect to postgresql://user:hunter2@host:5432/db")
    )
    hint = describe(error)
    assert "hunter2" not in hint and "://" not in hint
    assert "DATABASE_URL" in hint


def test_timeouts_and_connection_failures_are_distinguished():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    assert "timed out" in describe(APITimeoutError(request=request))
    assert "Could not reach" in describe(APIConnectionError(request=request))


def test_an_unrecognised_error_falls_back_without_leaking():
    hint = describe(ValueError("internal detail: /app/src/secret_path.py"))
    assert hint == GENERIC
    assert "secret_path" not in hint

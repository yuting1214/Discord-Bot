"""Turn an exception into something a deployer can act on.

A generic "something went wrong" tells the person running the bot nothing, and
the full exception cannot go into a Discord channel: provider errors quote the
API key (masked, but still), and database errors quote the connection string.

So the user gets the *category* and the setting to check, never the underlying
message. The full traceback stays in the service logs.
"""

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from sqlalchemy.exc import SQLAlchemyError

GENERIC = "Something went wrong. Check the service logs for details."


def describe(error: BaseException) -> str:
    """A short, actionable hint for ``error``.

    Ordered most specific first: several of these are subclasses of one another.
    """
    # Raised by llm/client.py when the provider's key variable is unset. Its own
    # message already names the variable, so it is safe and useful as-is.
    if isinstance(error, RuntimeError) and "is not set" in str(error):
        return f"⚠️ {error}"

    if isinstance(error, AuthenticationError):
        return (
            "🔑 The LLM provider rejected the API key. Check `OPENAI_API_KEY` "
            "(or `OPENROUTER_API_KEY` if `LLM_PROVIDER=openrouter`) — a stale or "
            "revoked key is the usual cause."
        )
    if isinstance(error, PermissionDeniedError):
        return (
            "🔒 The API key is valid but not permitted to use this model. Check the "
            "key's project access, or set `OPENAI_MODEL` to a model it can reach."
        )
    if isinstance(error, RateLimitError):
        return (
            "⏳ The LLM provider is rate-limiting, or the account is out of credit. "
            "Check the provider's usage dashboard."
        )
    if isinstance(error, NotFoundError):
        return (
            "🔍 The configured model was not found. Check `OPENAI_MODEL` / "
            "`OPENROUTER_MODEL`."
        )
    if isinstance(error, BadRequestError):
        return (
            "📝 The provider rejected the request. If you set `LLM_TEMPERATURE`, note "
            "that reasoning models accept only their own default."
        )
    if isinstance(error, APITimeoutError):
        return "⏱️ The LLM provider timed out. Try again, or raise `LLM_TIMEOUT`."
    if isinstance(error, APIConnectionError):
        return "🌐 Could not reach the LLM provider. It may be down, or egress is blocked."
    if isinstance(error, APIStatusError):
        return f"🛑 The LLM provider returned HTTP {error.status_code}. See the logs."

    if isinstance(error, SQLAlchemyError):
        return (
            "🗄️ The database is unreachable or rejected the query. Check that the "
            "PostgreSQL service is running and `DATABASE_URL` is set."
        )
    if isinstance(error, OSError):
        return "🔌 A network connection failed. Check the service's dependencies."

    return GENERIC

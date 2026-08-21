"""Provider clients.

OpenAI and OpenRouter speak the same wire protocol, so both are served by the
official ``openai`` SDK with a different ``base_url`` and key. Adding a further
OpenAI-compatible provider means one more entry in ``_PROVIDERS``.

Clients are cached per provider: each one owns an httpx connection pool, so
building a fresh client per message would discard warm connections and grow the
process's memory for no benefit.
"""

import os
from functools import cache

from openai import AsyncOpenAI, OpenAI

from src.llm.config import MAX_RETRIES, OPENROUTER_BASE_URL, REQUEST_TIMEOUT

# provider -> (env var holding the key, base_url or None for the vendor default)
_PROVIDERS: dict[str, tuple[str, str | None]] = {
    "openai": ("OPENAI_API_KEY", None),
    "openrouter": ("OPENROUTER_API_KEY", OPENROUTER_BASE_URL),
}


def _resolve(provider: str) -> tuple[str, str | None]:
    try:
        env_var, base_url = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(
            f"Unknown LLM provider {provider!r}. Expected one of: {', '.join(sorted(_PROVIDERS))}."
        ) from None

    api_key = os.getenv(env_var)
    if not api_key:
        raise RuntimeError(
            f"{env_var} is not set, which is required for the {provider!r} provider."
        )
    return api_key, base_url


@cache
def get_client(provider: str) -> OpenAI:
    """Return the cached synchronous client for ``provider``."""
    api_key, base_url = _resolve(provider)
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
    )


@cache
def get_async_client(provider: str) -> AsyncOpenAI:
    """Return the cached asynchronous client for ``provider``."""
    api_key, base_url = _resolve(provider)
    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
    )

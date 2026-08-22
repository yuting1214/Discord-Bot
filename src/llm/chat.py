"""Chat completions with conversation memory.

Replaces the previous LangChain ``prompt | model | StrOutputParser()`` chains
with a direct SDK call. The provider response carries token usage, so callers
can populate ``llm_usages`` with the counts that were actually billed rather
than a local re-estimate.

Reasoning models return ``reasoning_details`` alongside the answer. Those have
to be stored and replayed verbatim on the following turn, otherwise the model
restarts its reasoning from scratch instead of continuing it.
"""

import logging
from dataclasses import dataclass
from typing import Any

from openai import BadRequestError

from src.llm.client import get_async_client, get_client
from src.llm.config import (
    DEFAULT_PROVIDER,
    OPENAI_MODEL,
    OPENROUTER_MODEL,
    REASONING_ENABLED,
    SYSTEM_PROMPT,
    TEMPERATURE,
)

logger = logging.getLogger(__name__)

Message = dict[str, Any]

# Providers that accept OpenRouter's `reasoning` body field. OpenAI's own
# endpoint spells this differently, so it is not sent there.
_REASONING_PROVIDERS = {"openrouter"}


@dataclass(slots=True)
class ChatResult:
    """A completion, the usage the provider reported, and any reasoning trace."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_details: list[dict] | None = None


def _default_model(provider: str) -> str:
    return OPENROUTER_MODEL if provider == "openrouter" else OPENAI_MODEL


def build_messages(
    user_input: str,
    memory: list[Message] | None,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[Message]:
    """Assemble system prompt + prior turns + the new user turn.

    Assistant turns in ``memory`` keep any ``reasoning_details`` they carry; the
    provider requires them unmodified to resume a reasoning chain.
    """
    return [
        {"role": "system", "content": system_prompt},
        *(memory or []),
        {"role": "user", "content": user_input},
    ]


def _extra_body(provider: str, reasoning: bool) -> dict | None:
    if reasoning and provider in _REASONING_PROVIDERS:
        return {"reasoning": {"enabled": True}}
    return None


def _request_kwargs(provider: str, model: str | None, temperature: float | None, reasoning: bool) -> dict:
    kwargs: dict = {
        "model": model or _default_model(provider),
        "extra_body": _extra_body(provider, reasoning),
    }
    # Only sent when explicitly configured: reasoning models reject any value
    # but their own default and fail the whole call with a 400.
    if temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


def _rejected_temperature(error: BadRequestError) -> bool:
    return "temperature" in str(error).lower()


def _to_result(response) -> ChatResult:
    message = response.choices[0].message
    usage = response.usage
    return ChatResult(
        text=message.content or "",
        model=response.model,
        input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        # Unknown fields are preserved by the SDK's models (extra="allow").
        reasoning_details=getattr(message, "reasoning_details", None),
    )


def chat(
    user_input: str,
    memory: list[Message] | None = None,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    temperature: float | None = TEMPERATURE,
    reasoning: bool = REASONING_ENABLED,
) -> ChatResult:
    """Synchronous completion. Prefer :func:`achat` on the bot's hot path."""
    messages = build_messages(user_input, memory)
    kwargs = _request_kwargs(provider, model, temperature, reasoning)
    client = get_client(provider)
    try:
        response = client.chat.completions.create(messages=messages, **kwargs)
    except BadRequestError as e:
        if temperature is None or not _rejected_temperature(e):
            raise
        logger.warning("Model %s rejected temperature=%s; retrying without it", kwargs["model"], temperature)
        kwargs.pop("temperature")
        response = client.chat.completions.create(messages=messages, **kwargs)
    return _to_result(response)


async def achat(
    user_input: str,
    memory: list[Message] | None = None,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    temperature: float | None = TEMPERATURE,
    reasoning: bool = REASONING_ENABLED,
) -> ChatResult:
    """Asynchronous completion."""
    messages = build_messages(user_input, memory)
    kwargs = _request_kwargs(provider, model, temperature, reasoning)
    client = get_async_client(provider)
    try:
        response = await client.chat.completions.create(messages=messages, **kwargs)
    except BadRequestError as e:
        if temperature is None or not _rejected_temperature(e):
            raise
        logger.warning("Model %s rejected temperature=%s; retrying without it", kwargs["model"], temperature)
        kwargs.pop("temperature")
        response = await client.chat.completions.create(messages=messages, **kwargs)
    return _to_result(response)

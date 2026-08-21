"""Chat completions with conversation memory.

Replaces the previous LangChain ``prompt | model | StrOutputParser()`` chains
with a direct SDK call. The provider response carries token usage, so callers
can populate ``llm_usages`` with the counts that were actually billed rather
than a local re-estimate.

Reasoning models return ``reasoning_details`` alongside the answer. Those have
to be stored and replayed verbatim on the following turn, otherwise the model
restarts its reasoning from scratch instead of continuing it.
"""

from dataclasses import dataclass
from typing import Any

from llm.client import get_async_client, get_client
from llm.config import (
    DEFAULT_PROVIDER,
    OPENAI_MODEL,
    OPENROUTER_MODEL,
    REASONING_ENABLED,
    TEMPERATURE,
)
from llm.prompt.base_text_templates import TEXT_PROMPT_TEMPLATE_V1

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
    system_prompt: str = TEXT_PROMPT_TEMPLATE_V1,
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
    temperature: float = TEMPERATURE,
    reasoning: bool = REASONING_ENABLED,
) -> ChatResult:
    """Synchronous completion. Prefer :func:`achat` on the bot's hot path."""
    response = get_client(provider).chat.completions.create(
        model=model or _default_model(provider),
        messages=build_messages(user_input, memory),
        temperature=temperature,
        extra_body=_extra_body(provider, reasoning),
    )
    return _to_result(response)


async def achat(
    user_input: str,
    memory: list[Message] | None = None,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    temperature: float = TEMPERATURE,
    reasoning: bool = REASONING_ENABLED,
) -> ChatResult:
    """Asynchronous completion."""
    client = get_async_client(provider)
    response = await client.chat.completions.create(
        model=model or _default_model(provider),
        messages=build_messages(user_input, memory),
        temperature=temperature,
        extra_body=_extra_body(provider, reasoning),
    )
    return _to_result(response)

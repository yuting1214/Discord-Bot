"""Chat completions with conversation memory.

Replaces the previous LangChain ``prompt | model | StrOutputParser()`` chains
with a direct SDK call. The provider response carries token usage, so callers
can populate ``llm_usages`` with the counts that were actually billed rather
than a local re-estimate.
"""

from dataclasses import dataclass

from llm.client import get_async_client, get_client
from llm.config import (
    DEFAULT_PROVIDER,
    OPENAI_MODEL,
    OPENROUTER_MODEL,
    TEMPERATURE,
)
from llm.prompt.base_text_templates import TEXT_PROMPT_TEMPLATE_V1

Message = dict[str, str]


@dataclass(slots=True)
class ChatResult:
    """A completion plus the usage the provider reported for it."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int


def _default_model(provider: str) -> str:
    return OPENROUTER_MODEL if provider == "openrouter" else OPENAI_MODEL


def build_messages(
    user_input: str,
    memory: list[Message] | None,
    system_prompt: str = TEXT_PROMPT_TEMPLATE_V1,
) -> list[Message]:
    """Assemble system prompt + prior turns + the new user turn."""
    return [
        {"role": "system", "content": system_prompt},
        *(memory or []),
        {"role": "user", "content": user_input},
    ]


def _to_result(response) -> ChatResult:
    usage = response.usage
    return ChatResult(
        text=response.choices[0].message.content or "",
        model=response.model,
        input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
    )


def chat(
    user_input: str,
    memory: list[Message] | None = None,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    temperature: float = TEMPERATURE,
) -> ChatResult:
    """Synchronous completion. Prefer :func:`achat` on the bot's hot path."""
    response = get_client(provider).chat.completions.create(
        model=model or _default_model(provider),
        messages=build_messages(user_input, memory),
        temperature=temperature,
    )
    return _to_result(response)


async def achat(
    user_input: str,
    memory: list[Message] | None = None,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    temperature: float = TEMPERATURE,
) -> ChatResult:
    """Asynchronous completion."""
    client = get_async_client(provider)
    response = await client.chat.completions.create(
        model=model or _default_model(provider),
        messages=build_messages(user_input, memory),
        temperature=temperature,
    )
    return _to_result(response)

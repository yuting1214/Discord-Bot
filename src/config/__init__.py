"""Layered configuration: environment variables > `config/bot.yaml` > defaults.

The persona, the provider, the model and the search tuning used to be spread
across three modules and a dozen `os.getenv` calls, so changing the bot's
character meant editing Python. A deployer who forks this template now edits one
file.

**Environment still wins.** Railway variables are how a running service is
reconfigured without a rebuild, and this template publishes several of them.
Every variable name that worked before still works and still takes precedence
over the file -- `_ENV_OVERRIDES` below is the complete list, which doubles as
the documentation for it.

**Secrets are never read from here.** API keys and tokens stay environment-only,
because a YAML file in a public template repository is exactly where they must
not be. There is no mapping for any of them and there should never be one.

Imports nothing from ``src.backend``: ``src.llm`` depends on this, and must stay
free of the FastAPI application.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Resolved from this file rather than the working directory: the container's
# WORKDIR is /app and src/ lives at /app/src, so parents[2] is /app in both the
# image and a checkout.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "bot.yaml"


class LLMSettings(BaseModel):
    provider: str = "openai"
    models: dict[str, str] = Field(
        default_factory=lambda: {
            "openai": "gpt-5.6-luna",
            "openrouter": "openai/gpt-5.6-luna",
        }
    )
    # Unset by default and omitted from the request when unset. Reasoning models
    # reject any value but their own default and fail the whole call with a 400.
    temperature: float | None = None
    reasoning: bool = True
    timeout: float = 60.0
    max_retries: int = 2

    def model_for(self, provider: str) -> str:
        return self.models.get(provider, self.models.get("openai", "gpt-5.6-luna"))


class PromptSettings(BaseModel):
    summary: str = (
        "Summarise this conversation in two or three sentences. Name the topics "
        "discussed and any decision reached, in the language the user wrote in. "
        "Write only the summary, with no preamble."
    )
    system: str = (
        "You are a highly intelligent and versatile assistant. Your role is to help "
        "users with a wide variety of questions and tasks. You should provide "
        "accurate, concise, and informative responses. If the user asks a question, "
        "provide a clear and thorough answer. If the user requests assistance with a "
        "task, guide them step-by-step. Always be polite, respectful, and helpful. If "
        "you are unsure about something, it's better to admit it rather than provide "
        "incorrect information. Encourage users to ask follow-up questions if they "
        "need further assistance."
    )


class EmbeddingSettings(BaseModel):
    model: str = "text-embedding-3-small"
    # Changing this on a database that already holds vectors will not work: the
    # column is declared vector(dimensions) and existing rows keep the old width.
    dimensions: int = 1536


class SearchWeights(BaseModel):
    lexical: float = 1.0
    semantic: float = 1.0


class SearchSettings(BaseModel):
    top_n: int = 5
    rrf_k: int = 60
    # Cosine distance past which a session is not a match at all. Measured, not
    # chosen -- see src/backend/search/service.py.
    semantic_max_distance: float = 0.75
    weights: SearchWeights = Field(default_factory=SearchWeights)


class SummarySettings(BaseModel):
    """One embedding per session instead of one per turn.

    A turn-level embedding is generated on every message -- O(turns) provider
    calls -- and most turns are not worth one. A session summary is O(sessions),
    roughly a 10-20x reduction, and is dense and topical rather than
    conversational.
    """

    enabled: bool = True
    # A session left active is never deactivated and so never summarised. The
    # sweep closes that hole.
    idle_minutes: int = 60
    sweep_interval_minutes: int = 15
    # Sessions summarised per sweep. Bounds the provider spend of a single pass
    # over a backlog.
    batch_size: int = 20


class MemorySettings(BaseModel):
    # Prior turns replayed to the model. Deliberately the only knob here: a
    # token budget is a better idea and is not implemented, and a setting that
    # does nothing is worse than no setting.
    window_size: int = 3


class BotConfig(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    prompts: PromptSettings = Field(default_factory=PromptSettings)
    embeddings: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    summary: SummarySettings = Field(default_factory=SummarySettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)


def _boolean(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _optional_float(raw: str) -> float | None:
    """An empty variable means "unset", not "zero"."""
    raw = raw.strip()
    return float(raw) if raw else None


# (environment variable, dotted path, parser). Every name here predates the YAML
# file and is published in the template, so none of them may be renamed.
_ENV_OVERRIDES: tuple[tuple[str, str, Callable[[str], object]], ...] = (
    ("LLM_PROVIDER", "llm.provider", str),
    ("OPENAI_MODEL", "llm.models.openai", str),
    ("OPENROUTER_MODEL", "llm.models.openrouter", str),
    ("LLM_TEMPERATURE", "llm.temperature", _optional_float),
    ("LLM_REASONING", "llm.reasoning", _boolean),
    ("LLM_TIMEOUT", "llm.timeout", float),
    ("LLM_MAX_RETRIES", "llm.max_retries", int),
    ("EMBEDDING_MODEL", "embeddings.model", str),
    ("EMBEDDING_DIM", "embeddings.dimensions", int),
    ("SEARCH_TOP_N", "search.top_n", int),
    ("SEARCH_RRF_K", "search.rrf_k", int),
    ("SEARCH_LEXICAL_WEIGHT", "search.weights.lexical", float),
    ("SEARCH_SEMANTIC_WEIGHT", "search.weights.semantic", float),
    ("SEARCH_SEMANTIC_MAX_DISTANCE", "search.semantic_max_distance", float),
    ("SUMMARY_ENABLED", "summary.enabled", _boolean),
    ("SUMMARY_IDLE_MINUTES", "summary.idle_minutes", int),
    ("SUMMARY_SWEEP_INTERVAL_MINUTES", "summary.sweep_interval_minutes", int),
    ("SUMMARY_BATCH_SIZE", "summary.batch_size", int),
    ("MEMORY_WINDOW_SIZE", "memory.window_size", int),
)


def _assign(data: dict, dotted: str, value: object) -> None:
    *parents, leaf = dotted.split(".")
    node = data
    for key in parents:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):  # a scalar where the schema wants a mapping
            return
    node[leaf] = value


def apply_env_overrides(data: dict, environ: dict[str, str] | None = None) -> dict:
    """Overlay environment variables onto parsed YAML, in place."""
    environ = os.environ if environ is None else environ
    for name, dotted, parse in _ENV_OVERRIDES:
        if name not in environ:
            continue
        try:
            _assign(data, dotted, parse(environ[name]))
        except (TypeError, ValueError):
            # One malformed variable must not take the process down with it.
            logger.warning("Ignoring %s=%r: not a valid value", name, environ[name])
    return data


def load_config(path: Path | None = None, environ: dict[str, str] | None = None) -> BotConfig:
    """Read the file if it exists, overlay the environment, validate.

    A missing file is not an error -- the defaults are a complete configuration,
    so the bot runs with no YAML at all.
    """
    source = path or Path(os.getenv("BOT_CONFIG", DEFAULT_CONFIG_PATH))
    data: dict = {}
    if source.is_file():
        try:
            data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            logger.exception("Could not parse %s; falling back to defaults", source)
            data = {}
        if not isinstance(data, dict):
            logger.warning("%s is not a mapping; ignoring it", source)
            data = {}
    return BotConfig.model_validate(apply_env_overrides(data, environ))


bot_config = load_config()

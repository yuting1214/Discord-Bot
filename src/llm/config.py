"""Configuration for the LLM layer.

Values now come from :mod:`src.config` -- `config/bot.yaml` with environment
variables layered on top -- rather than from `os.getenv` calls scattered here.
The module-level names are kept because they are the public surface of this
package and are imported by call sites as defaults.

Deliberately free of any ``backend`` import: importing ``llm`` must never pull
in the FastAPI application.
"""

from dotenv import load_dotenv

from src.config import bot_config

load_dotenv()

_llm = bot_config.llm

# "openai" or "openrouter"
DEFAULT_PROVIDER = _llm.provider

OPENAI_MODEL = _llm.model_for("openai")
OPENROUTER_MODEL = _llm.model_for("openrouter")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Unset by default, and omitted from the request when unset. Reasoning models
# (including the default gpt-5.6-luna) reject any value but their own default,
# so sending one unconditionally fails every call with a 400.
TEMPERATURE: float | None = _llm.temperature
REQUEST_TIMEOUT = _llm.timeout
MAX_RETRIES = _llm.max_retries

# Reasoning is requested through OpenRouter's `reasoning` body field. The model
# returns `reasoning_details`, which must be handed back verbatim on the next
# turn for it to continue reasoning rather than restart.
REASONING_ENABLED = _llm.reasoning

# The persona. Lives in config/bot.yaml so it can be changed without touching
# Python; see src/llm/prompt/base_text_templates.py for the historical name.
SYSTEM_PROMPT = bot_config.prompts.system

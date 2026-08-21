"""Configuration for the LLM layer.

Deliberately free of any ``backend`` import: importing ``llm`` must never pull in
the FastAPI application (or its import-time argparse).

Every model id is overridable by environment variable. Hardcoded model ids are
what left the previous revision of this template pinned to gpt-3.5-turbo-0125.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# "openai" or "openrouter"
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.6-luna")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Unset by default, and omitted from the request when unset. Reasoning models
# (including the default gpt-5.6-luna) reject any value but their own default,
# so sending one unconditionally fails every call with a 400.
_temperature = os.getenv("LLM_TEMPERATURE", "").strip()
TEMPERATURE: float | None = float(_temperature) if _temperature else None
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# Reasoning is requested through OpenRouter's `reasoning` body field. The model
# returns `reasoning_details`, which must be handed back verbatim on the next
# turn for it to continue reasoning rather than restart.
REASONING_ENABLED = os.getenv("LLM_REASONING", "true").lower() in ("1", "true", "yes", "on")

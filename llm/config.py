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

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.5"))
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

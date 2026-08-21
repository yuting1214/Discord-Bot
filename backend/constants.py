import pytz
from backend.fastapi.core.init_settings import global_settings as settings

TIMEZONE="Etc/GMT-4"
CURRENT_TIMEZONE=pytz.timezone(TIMEZONE)
OPENROUTER_LLM_ENDPOINT="openai/gpt-3.5-turbo-0125"
OPENAI_LLM_ENDPOINT="gpt-4o-mini"
TEMPERATURE=0.5
MEMORY_WINDOW_SIZE=3
API_BASE_URL_SYNC =settings.API_BASE_URL_SYNC
API_BASE_URL_ASYNC =settings.API_BASE_URL_ASYNC
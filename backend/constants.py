import pytz

from backend.fastapi.core.init_settings import global_settings as settings

TIMEZONE="Etc/GMT-4"
CURRENT_TIMEZONE=pytz.timezone(TIMEZONE)
MEMORY_WINDOW_SIZE=3
API_BASE_URL_SYNC =settings.API_BASE_URL_SYNC
API_BASE_URL_ASYNC =settings.API_BASE_URL_ASYNC

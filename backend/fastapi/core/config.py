import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = "Discord LLM Bot"
    APP_VERSION: str = "0.2.0"

    # Username and Password for login
    USER_NAME: str = ""
    PASSWORD: str = ""

    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 5000

    # Signs session cookies. Generated per process when unset, which means
    # sessions do not survive a restart; set it to keep them.
    SECRET_KEY: str = ""

    # API KEY
    OPENAI_API_KEY: str

    @property
    def DB_URL(self):
        if self.ENV_MODE == "dev":
            return self.DEV_DB_URL
        else:
            if self.DATABASE_URL:
                return self.DATABASE_URL
            else:
                return f'{self.DB_ENGINE}://{self.DB_USERNAME}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    @property
    def ASYNC_DB_URL(self):
        if self.ENV_MODE == "dev":
            return "sqlite+aiosqlite:///./dev.db"
        else:
            if self.DATABASE_URL:
                URL_split = self.DATABASE_URL.split("://")
                return f"{URL_split[0]}+asyncpg://{URL_split[1]}"
            else:
                return f'{self.DB_ENGINE}+asyncpg://{self.DB_USERNAME}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'


class DevSettings(Settings):
    # Environment mode: 'dev' or 'prod'
    ENV_MODE: str = 'dev'

    # Database settings for development
    DEV_DB_URL: str = "sqlite:///./dev.db"

    model_config = SettingsConfigDict(env_file=".env", extra='allow')


class ProdSettings(Settings):
    # Environment mode: 'dev' or 'prod'
    ENV_MODE: str = 'prod'

    HOST: str = "0.0.0.0"

    # Database settings for production
    DB_ENGINE: str = ""
    DB_USERNAME: str = ""
    DB_PASS: str = ""
    DB_HOST: str = ""
    DB_PORT: str = ""
    DB_NAME: str = ""

    # Extra Database settings for deploying on Railway; if you provide DATABASE_URL, the above settings will be ignored
    DATABASE_URL: str = ""

    # Public base URL of this service
    HOST_URL: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra='allow')


def get_settings(env_mode: str | None = None):
    """Build settings for ``env_mode``, defaulting to the ENV_MODE variable.

    Fields are populated by pydantic-settings from the environment and .env, so
    they must not carry os.getenv() defaults: those are evaluated once at import
    and shadow the settings machinery.
    """
    if env_mode is None:
        env_mode = os.getenv("ENV_MODE", "dev")
    return DevSettings() if env_mode == "dev" else ProdSettings()

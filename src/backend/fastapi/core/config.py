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
    def ASYNC_DB_URL(self):
        if self.ENV_MODE == "dev":
            return "sqlite+aiosqlite:///./dev.db"
        if self.DATABASE_URL:
            scheme, _, rest = self.DATABASE_URL.partition("://")
            return f"{scheme}+asyncpg://{rest}"
        self._require_db_parts()
        return f'{self.DB_ENGINE}+asyncpg://{self.DB_USERNAME}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    def _require_db_parts(self) -> None:
        """Fail with something a deployer can act on.

        Assembling a URL from blank parts produced
        "invalid literal for int() with base 10: ''" from deep inside
        SQLAlchemy's URL parser, which says nothing about what to set.
        """
        missing = [
            name
            for name in ("DB_ENGINE", "DB_USERNAME", "DB_HOST", "DB_PORT", "DB_NAME")
            if not getattr(self, name, "")
        ]
        if missing:
            raise RuntimeError(
                "Database is not configured in prod mode. Set DATABASE_URL, or all of: "
                + ", ".join(missing)
            )


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

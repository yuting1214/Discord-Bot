"""Credentials for the protected documentation routes.

Previously this compared the submitted form against os.getenv("USER_NAME") and
os.getenv("PASSWORD"). The Railway template ships both as empty strings, so on a
default deploy "" == "" held and submitting an empty login form authenticated,
exposing /docs and /redoc to anyone. Credentials are now generated when unset
and never compared as empty.
"""

import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache

from src.backend.fastapi.core.init_settings import global_settings as settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str
    generated: bool


@lru_cache(maxsize=1)
def get_credentials() -> Credentials:
    """Resolve the docs credentials, generating any that are missing.

    Cached so a generated password stays stable for the life of the process.
    """
    username = settings.USER_NAME or "admin"
    password = settings.PASSWORD or secrets.token_urlsafe(24)
    generated = not (settings.USER_NAME and settings.PASSWORD)
    return Credentials(username=username, password=password, generated=generated)


def log_credentials_once() -> None:
    """Print generated credentials at startup, so a deployer can still get in."""
    credentials = get_credentials()
    if credentials.generated:
        logger.warning(
            "USER_NAME/PASSWORD were not set. Generated docs credentials -- "
            "username: %s  password: %s  (set both to keep them across restarts)",
            credentials.username,
            credentials.password,
        )


def authenticate_user(username: str, password: str) -> bool:
    """Constant-time credential check.

    compare_digest keeps the comparison time independent of how much of the
    value matched, so responses cannot be used to probe it character by
    character.
    """
    if not username or not password:
        return False

    credentials = get_credentials()
    correct_username = secrets.compare_digest(username, credentials.username)
    correct_password = secrets.compare_digest(password, credentials.password)
    # Both are evaluated unconditionally: `and` would short-circuit and leak
    # whether the username alone was right.
    return correct_username & correct_password

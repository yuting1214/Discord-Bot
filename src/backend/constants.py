from datetime import UTC

from src.config import bot_config

# Timestamps are stored as naive UTC so that values set by the application match
# the database's own func.now() defaults. The previous code mixed the two: some
# columns defaulted to server time while others were written in Etc/GMT-4, which
# made ordering and duration arithmetic across them wrong.
TIMEZONE = UTC
MEMORY_WINDOW_SIZE = bot_config.memory.window_size


def utcnow():
    """Naive UTC, matching the DateTime columns."""
    from datetime import datetime

    return datetime.now(UTC).replace(tzinfo=None)

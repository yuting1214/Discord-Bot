from datetime import UTC

# Timestamps are stored as naive UTC so that values set by the application match
# the database's own func.now() defaults. The previous code mixed the two: some
# columns defaulted to server time while others were written in Etc/GMT-4, which
# made ordering and duration arithmetic across them wrong.
TIMEZONE = UTC
MEMORY_WINDOW_SIZE = 3


def utcnow():
    """Naive UTC, matching the DateTime columns."""
    from datetime import datetime

    return datetime.now(UTC).replace(tzinfo=None)

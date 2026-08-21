"""Process-wide settings.

Configuration comes from the environment, not from command-line arguments. The
previous version parsed argv at import time, which meant importing any module in
the package consumed the arguments of whatever was actually running -- pytest,
uvicorn, or a REPL -- and aborted on anything it did not recognise.
"""

from src.backend.fastapi.core.config import get_settings

settings = get_settings()

# Save settings for import in other modules
global_settings = settings

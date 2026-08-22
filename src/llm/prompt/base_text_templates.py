"""The default persona.

Kept as a module constant for backwards compatibility -- it was importable here
before there was a configuration file. The value the bot actually uses is
``src.config.bot_config.prompts.system``, which this mirrors: edit
``config/bot.yaml``, not this file.
"""

from src.config import bot_config

TEXT_PROMPT_TEMPLATE_V1 = bot_config.prompts.system

import asyncio
import logging
from functools import wraps

import discord

from backend.discord.bot import DiscordClient, Sender
from backend.discord.run_async import (
    complete_session_chat,
    resume_session,
    search_messages_and_list_sessions,
)

logger = logging.getLogger(__name__)

# asyncio only holds a weak reference to a running task, so a task that nothing
# else references can be garbage collected mid-flight. Keep strong references
# until each one finishes.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _context(interaction: discord.Interaction) -> dict[str, str]:
    """Pull the identifiers the session layer needs off an interaction."""
    return {
        "server_discord_id": str(interaction.guild.id),
        "server_name": str(interaction.guild.name),
        "owner_discord_id": str(interaction.guild.owner_id),
        "channel_discord_id": str(interaction.channel.id),
        "channel_name": str(interaction.channel.name),
        "user_discord_id": str(interaction.user.id),
        "user_name": str(interaction.user.name),
    }


async def _reject_if_dm(interaction: discord.Interaction) -> bool:
    """Guard commands that require guild context.

    In a DM ``interaction.guild`` is None, so reading guild attributes raised
    AttributeError and the command failed with no reply at all.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server, not in a direct message.",
            ephemeral=True,
        )
        return True
    return False


async def _respond(interaction: discord.Interaction, sender: Sender, user_input: str, result: dict) -> None:
    if result.get("error"):
        logger.error("Command failed: %s", result["error"])
    await sender.send_message(interaction, user_input, result["message"])


def session_chat_async_decorator(client: DiscordClient, sender: Sender, is_group: bool, is_new_session: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            if await _reject_if_dm(interaction):
                return

            ctx = _context(interaction)
            await interaction.response.defer()

            # Deferred so the work can outlive Discord's 3s interaction window.
            _spawn(handle_long_operation(interaction, sender, user_input, is_group, is_new_session, **ctx))

        return wrapper
    return decorator


async def handle_long_operation(
        interaction: discord.Interaction,
        sender: Sender,
        user_input: str,
        is_group: bool,
        is_new_session: bool,
        *,
        server_discord_id: str,
        server_name: str,
        owner_discord_id: str,
        channel_discord_id: str,
        channel_name: str,
        user_discord_id: str,
        user_name: str,
    ):
    try:
        llm_response_dict = await complete_session_chat(
            server_discord_id, server_name, owner_discord_id, channel_discord_id, channel_name,
            user_discord_id, user_name, user_input, is_group, is_new_session
        )
        if "error" in llm_response_dict:
            logger.error("Chat failed: %s", llm_response_dict["error"])
            await interaction.followup.send(
                "> **Error: Something went wrong, please try again later!**"
            )
            return
        await sender.send_message(interaction, user_input, llm_response_dict["llm_response"])
    except Exception:
        # Runs detached from the command, so an unlogged failure here would be
        # invisible on the server and silent to the user.
        logger.exception("Unhandled error while completing a session chat")
        try:
            await interaction.followup.send(
                "> **Error: Something went wrong, please try again later!**"
            )
        except discord.HTTPException:
            logger.exception("Could not deliver the error message to Discord")


def _simple_command_decorator(sender: Sender, is_group: bool, operation):
    """Shared body for the commands that reply inline rather than deferring work."""
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            if await _reject_if_dm(interaction):
                return

            ctx = _context(interaction)
            await interaction.response.defer()

            try:
                message_dict = await operation(
                    ctx["server_discord_id"], ctx["server_name"], ctx["owner_discord_id"],
                    ctx["channel_discord_id"], ctx["channel_name"], ctx["user_discord_id"],
                    ctx["user_name"], user_input, is_group
                )
                await _respond(interaction, sender, user_input, message_dict)
            except Exception:
                logger.exception("Unhandled error in %s", operation.__name__)
                await interaction.followup.send(
                    "> **Error: Something went wrong, please try again later!**"
                )
        return wrapper
    return decorator


def session_resume_async_decorator(client: DiscordClient, sender: Sender, is_group: bool):
    return _simple_command_decorator(sender, is_group, resume_session)


def search_async_decorator(client: DiscordClient, sender: Sender, is_group: bool):
    return _simple_command_decorator(sender, is_group, search_messages_and_list_sessions)

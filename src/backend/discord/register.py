import os

import discord

from src.backend.discord.bot import DiscordClient, Sender
from src.backend.discord.decorator_async import (
    search_async_decorator,
    session_chat_async_decorator,
    session_resume_async_decorator,
)


def build_client() -> DiscordClient:
    """Construct the client and register every slash command on its tree."""
    client = DiscordClient()
    sender = Sender()

    @client.tree.command(name="start_session", description="Start a New Single Session.")
    @discord.app_commands.rename(user_input="message")
    @discord.app_commands.describe(user_input="What you want to ask. Starts a fresh single session.")
    @session_chat_async_decorator(client, sender, is_group=False, is_new_session=True)
    async def start_single_session(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="bot", description="Send a Message in an Existing Single Session.")
    @discord.app_commands.rename(user_input="message")
    @discord.app_commands.describe(user_input="What you want to say in your current single session.")
    @session_chat_async_decorator(client, sender, is_group=False, is_new_session=False)
    async def single_chat(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="start_group_session", description="Start a New Group Session.")
    @discord.app_commands.rename(user_input="message")
    @discord.app_commands.describe(user_input="What you want to ask. Starts a fresh group session in this channel.")
    @session_chat_async_decorator(client, sender, is_group=True, is_new_session=True)
    async def start_group_session(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="bot_group", description="Send a Message in an Existing Group Session.")
    @discord.app_commands.rename(user_input="message")
    @discord.app_commands.describe(user_input="What you want to say in this channel's group session.")
    @session_chat_async_decorator(client, sender, is_group=True, is_new_session=False)
    async def group_chat(interaction: discord.Interaction, *, user_input: str):
        pass 

    @client.tree.command(name="resume_session", description="Resume a Previous Single Session")
    @discord.app_commands.rename(user_input="session_id")
    @discord.app_commands.describe(user_input="ID of the session to resume — copy one from /search results.")
    @session_resume_async_decorator(client, sender, is_group=False)
    async def resume_session(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="resume_group_session", description="Resume a Previous Group Session")
    @discord.app_commands.rename(user_input="session_id")
    @discord.app_commands.describe(user_input="ID of the group session to resume — copy one from /search_group.")
    @session_resume_async_decorator(client, sender, is_group=True)
    async def resume_group_session(interaction: discord.Interaction, *, user_input: str):
        pass 

    @client.tree.command(name="search", description="Search previous messages in Single Sessions.")
    @discord.app_commands.rename(user_input="query")
    @discord.app_commands.describe(user_input="What to look for in your past messages.")
    @search_async_decorator(client, sender, is_group=False)
    async def search(interaction: discord.Interaction, *, user_input: str):
        pass 

    @client.tree.command(name="search_group", description="Search previous messages in Group Sessions.")
    @discord.app_commands.rename(user_input="query")
    @discord.app_commands.describe(user_input="What to look for in this channel's group messages.")
    @search_async_decorator(client, sender, is_group=True)
    async def search_group(interaction: discord.Interaction, *, user_input: str):
        pass 

    return client


def discord_token() -> str:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        # Passing None reaches discord.py as an opaque TypeError; say what is
        # actually wrong, since this is the most common first-deploy mistake.
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Create a bot at "
            "https://discord.com/developers/applications and set its token."
        )
    return token


async def run_discord_bot(client: DiscordClient) -> None:
    """Run the bot on the *current* event loop until it is cancelled.

    Deliberately `client.start()` rather than `client.run()`: run() builds and
    owns an event loop of its own. Running the bot on a second loop while the
    web application runs on another means the two share one SQLAlchemy engine
    across event loops, and a pooled connection created on one loop fails on the
    other with "got Future attached to a different loop".
    """
    await client.start(discord_token())
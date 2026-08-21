import os
import json
import discord
from backend.discord.bot import DiscordClient, Sender
from backend.discord.decorator_async import (
    session_chat_async_decorator,
    session_resume_async_decorator,
    search_async_decorator
)


def discord_bot_run():
    client = DiscordClient()
    sender = Sender()

    @client.tree.command(name="start_session", description="Start a New Single Session.")
    @session_chat_async_decorator(client, sender, is_group=False, is_new_session=True)
    async def start_single_session(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="bot", description="Send a Message in an Existing Single Session.")
    @session_chat_async_decorator(client, sender, is_group=False, is_new_session=False)
    async def single_chat(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="start_group_session", description="Start a New Group Session.")
    @session_chat_async_decorator(client, sender, is_group=True, is_new_session=True)
    async def start_group_session(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="bot_group", description="Send a Message in an Existing Group Session.")
    @session_chat_async_decorator(client, sender, is_group=True, is_new_session=False)
    async def group_chat(interaction: discord.Interaction, *, user_input: str):
        pass 

    @client.tree.command(name="resume_session", description="Resume a Previous Single Session")
    @session_resume_async_decorator(client, sender, is_group=False)
    async def resume_session(interaction: discord.Interaction, *, user_input: str):
        pass  

    @client.tree.command(name="resume_group_session", description="Resume a Previous Group Session")
    @session_resume_async_decorator(client, sender, is_group=True)
    async def resume_group_session(interaction: discord.Interaction, *, user_input: str):
        pass 

    @client.tree.command(name="search", description="Search previous messages in Single Sessions.")
    @search_async_decorator(client, sender, is_group=False)
    async def search(interaction: discord.Interaction, *, user_input: str):
        pass 

    @client.tree.command(name="search_group", description="Search previous messages in Group Sessions.")
    @search_async_decorator(client, sender, is_group=True)
    async def search_group(interaction: discord.Interaction, *, user_input: str):
        pass 

    client.run(os.getenv('DISCORD_TOKEN'))
import json
import asyncio
import discord
from functools import wraps
from backend.discord.bot import DiscordClient, Sender
from backend.discord.run_async import (
    resume_session,
    complete_session_chat,
    search_messages_and_list_sessions,
)

# Async decorator
def session_chat_async_decorator(client: DiscordClient, sender: Sender, is_group: bool, is_new_session: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            server_discord_id = str(interaction.guild.id)
            server_name = str(interaction.guild.name)
            owner_discord_id = str(interaction.guild.owner_id)
            channel_discord_id = str(interaction.channel.id)
            channel_name = str(interaction.channel.name)
            user_discord_id = str(interaction.user.id)
            user_name = str(interaction.user.name)

            if interaction.user == client.user:
                return

            await interaction.response.defer()
            
            # Run the long operation in an asyncio task
            asyncio.create_task(handle_long_operation(
                interaction, server_discord_id, server_name, owner_discord_id, channel_discord_id, channel_name,
                user_discord_id, user_name, user_input, is_group, is_new_session, sender
            ))

        return wrapper
    return decorator

async def handle_long_operation(
        interaction: discord.Interaction,
        server_discord_id: str,
        server_name: str,
        owner_discord_id: str,
        channel_discord_id: str,
        channel_name: str,
        user_discord_id: str,
        user_name: str,
        user_input: str,
        is_group: bool,
        is_new_session: bool,
        sender: Sender
    ):
    try:
        llm_response_dict = await complete_session_chat(
            server_discord_id, server_name, owner_discord_id, channel_discord_id, channel_name, user_discord_id, user_name, user_input, is_group, is_new_session
        )
        response = llm_response_dict["llm_response"]
        await sender.send_message(interaction, user_input, response)
    except Exception as e:
        error_message = str(e)
        await interaction.followup.send(f'{error_message}')

def session_resume_async_decorator(client: DiscordClient, sender: Sender, is_group: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            server_discord_id = str(interaction.guild.id)
            server_name = str(interaction.guild.name)
            owner_discord_id = str(interaction.guild.owner_id)
            channel_discord_id = str(interaction.channel.id)
            channel_name = str(interaction.channel.name)
            user_discord_id = str(interaction.user.id)
            user_name = str(interaction.user.name)

            if interaction.user == client.user:
                return

            await interaction.response.defer()

            try:
                # Ensure resume_session is an async function
                message_dict = await resume_session(
                    server_discord_id, server_name, owner_discord_id, channel_discord_id, channel_name, user_discord_id, user_name, user_input, is_group
                )
                response = message_dict["message"]
                await sender.send_message(interaction, user_input, response)
            except Exception as e:
                error_message = str(e)
                await interaction.followup.send(f'{error_message}')
        return wrapper
    return decorator

def search_async_decorator(client: DiscordClient, sender: Sender, is_group: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            server_discord_id = str(interaction.guild.id)
            server_name = str(interaction.guild.name)
            owner_discord_id = str(interaction.guild.owner_id)
            channel_discord_id = str(interaction.channel.id)
            channel_name = str(interaction.channel.name)
            user_discord_id = str(interaction.user.id)
            user_name = str(interaction.user.name)

            if interaction.user == client.user:
                return

            await interaction.response.defer()

            try:
                # Ensure search_messages_and_list_sessions is an async function
                message_dict = await search_messages_and_list_sessions(
                    server_discord_id, server_name, owner_discord_id, channel_discord_id, channel_name, user_discord_id, user_name, user_input, is_group
                )
                response = message_dict["message"]
                await sender.send_message(interaction, user_input, response)
            except Exception as e:
                error_message = str(e)
                await interaction.followup.send(f'{error_message}')
        return wrapper
    return decorator

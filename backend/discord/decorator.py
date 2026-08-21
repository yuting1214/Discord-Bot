from functools import wraps

import discord

from backend.discord.bot import DiscordClient, Sender
from backend.discord.run import complete_session_chat, resume_session, search_messages_and_list_sessions


def session_chat_decorator(client: DiscordClient, sender: Sender, is_group: bool, is_new_session: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            channel_id = str(interaction.channel.id)
            user_discord_id = str(interaction.user.id)
            user_name = str(interaction.user.name)

            if interaction.user == client.user:
                return

            await interaction.response.defer()
            llm_response_dict = complete_session_chat(
                channel_id, user_discord_id, user_name, user_input, is_group, is_new_session
            )
            response = llm_response_dict["llm_response"]
            await sender.send_message(interaction, user_input, response)

        return wrapper
    return decorator

def session_resume_decorator(client: DiscordClient, sender: Sender, is_group: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            channel_id = str(interaction.channel.id)
            user_discord_id = str(interaction.user.id)
            user_name = str(interaction.user.name)

            if interaction.user == client.user:
                return

            await interaction.response.defer()
            message_dict = resume_session(
                channel_id, user_discord_id, user_name, user_input, is_group
            )
            response = message_dict["message"]
            await sender.send_message(interaction, user_input, response)

        return wrapper
    return decorator

def search_async_decorator(client: DiscordClient, sender: Sender, is_group: bool):
    def decorator(func):
        @wraps(func)
        async def wrapper(interaction: discord.Interaction, *, user_input: str):
            channel_id = str(interaction.channel.id)
            user_discord_id = str(interaction.user.id)
            user_name = str(interaction.user.name)

            if interaction.user == client.user:
                return

            await interaction.response.defer()
            message_dict = search_messages_and_list_sessions(
                channel_id, user_discord_id, user_name, user_input, is_group
            )
            response = message_dict["message"]
            await sender.send_message(interaction, user_input, response)

        return wrapper
    return decorator
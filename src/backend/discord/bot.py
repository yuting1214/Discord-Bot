import logging

import discord

logger = logging.getLogger(__name__)

# Discord's hard limit for a single message.
MESSAGE_LIMIT = 2000

# This bot exposes slash commands only, so it needs no privileged intents.
# `Intents.default()` deliberately excludes message_content, members and
# presences: requesting message_content without enabling it in the Discord
# Developer Portal makes login fail outright with PrivilegedIntentsRequired.
intents = discord.Intents.default()


class DiscordClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="LLM-based ChatBot!"
            ),
        )
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        """Sync the command tree exactly once, before the gateway connects.

        Syncing from on_ready instead would re-run on every reconnect, and the
        sync endpoint is sharply rate limited.
        """
        synced = await self.tree.sync()
        logger.info("Synced %d application command(s)", len(synced))

    async def on_ready(self) -> None:
        logger.info("%s is connected to %d guild(s)", self.user, len(self.guilds))
        for guild in self.guilds:
            logger.debug("  guild: %s (id: %s)", guild.name, guild.id)


def chunk_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split ``text`` into Discord-sized pieces, preferring clean boundaries.

    Tries paragraph, then line, then word boundaries before falling back to a
    hard cut, so responses are not severed mid-word.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        # Prefer the latest boundary available within the window.
        split = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if split <= 0:
            split = limit  # no boundary: hard cut rather than emit nothing
        chunks.append(remaining[:split].rstrip())
        remaining = remaining[split:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


class Sender:
    async def send_message(
        self, interaction: discord.Interaction, user_message: str, llm_response: str
    ) -> None:
        response = f'> **{user_message}** - <@{interaction.user.id}> \n\n {llm_response}'
        try:
            for chunk in chunk_message(response):
                await interaction.followup.send(chunk)
        except discord.HTTPException:
            # Log the cause rather than discarding it; the user only ever saw a
            # generic failure string before.
            logger.exception("Failed to deliver response to Discord")
            await interaction.followup.send(
                "> **Error: Something went wrong, please try again later!**"
            )

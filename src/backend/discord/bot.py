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
        """Sync the command tree, but only when the definitions actually changed.

        Syncing from on_ready instead would re-run on every reconnect, and the
        sync endpoint is sharply rate limited.

        Re-registering identical commands invalidates the definitions cached by
        every connected Discord client, which then answers the next invocation
        with "This command is outdated, please try again in a few minutes" until
        the user reloads. Skipping a no-op sync keeps that to deploys that really
        do change the commands.
        """
        if not await self._definitions_changed():
            logger.info("Application commands unchanged; skipping sync")
            return

        synced = await self.tree.sync()
        logger.info("Synced %d application command(s)", len(synced))

    async def _definitions_changed(self) -> bool:
        """Compare the local command tree with what Discord already has."""
        try:
            registered = await self.tree.fetch_commands()
        except discord.HTTPException:
            logger.warning("Could not fetch registered commands; syncing anyway", exc_info=True)
            return True

        return _fingerprint(self.tree.get_commands()) != _fingerprint(registered)

    async def on_ready(self) -> None:
        logger.info("%s is connected to %d guild(s)", self.user, len(self.guilds))
        for guild in self.guilds:
            logger.debug("  guild: %s (id: %s)", guild.name, guild.id)


def _fingerprint(commands) -> set[tuple]:
    """A comparable signature of a command set, local or remote.

    Local commands expose `parameters`, fetched ones expose `options`; both carry
    the same fields, so one shape serves for the comparison.
    """
    signature = set()
    for command in commands:
        options = getattr(command, "parameters", None) or getattr(command, "options", []) or []
        signature.add((
            command.name,
            command.description,
            tuple(sorted(
                (
                    getattr(o, "display_name", None) or o.name,
                    o.description,
                    int(getattr(o.type, "value", o.type)),
                    bool(o.required),
                )
                for o in options
            )),
        ))
    return signature


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

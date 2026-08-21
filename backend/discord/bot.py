import discord

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True  
intents.guild_messages = True

class DiscordClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.synced = False
        self.added = False
        self.tree = discord.app_commands.CommandTree(self)
        self.activity = discord.Activity(type=discord.ActivityType.watching, name="LLM-based ChatBot!")

    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            await self.tree.sync()
            self.synced = True
        if not self.added:
            self.added = True
        print(f'{self.user} is connected to the following guild(s):')
            
        for guild in self.guilds:
            print(f'{guild.name} (id: {guild.id})')

class Sender:
    async def send_message(self, interaction: discord.Interaction, user_message: str, llm_response: str):
        try:
            user_id = interaction.user.id
            response = f'> **{user_message}** - <@{str(user_id)}> \n\n {llm_response}'
            
            # Split the response into chunks of 2000 characters for Discord
            response_chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
            
            # Send each chunk separately
            for chunk in response_chunks:
                await interaction.followup.send(chunk)
        except Exception as e:
            await interaction.followup.send('> **Error: Something went wrong, please try again later!**')
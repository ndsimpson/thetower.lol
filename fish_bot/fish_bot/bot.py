# Standard library imports
import logging
import os
from pathlib import Path

# Third-party imports
import django
import discord
from discord.ext import commands
from discord.ext.commands import Context

# Local imports
from fish_bot.exceptions import UserUnauthorized, ChannelUnauthorized
from fish_bot.utils import CogAutoReload, CogLoader, ConfigManager, BaseFileMonitor

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Discord setup
intents = discord.Intents.default()
intents.presences = True
intents.message_content = True
intents.members = True


class DiscordBot(commands.Bot, BaseFileMonitor):
    def __init__(self) -> None:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
        django.setup()
        self.config = ConfigManager()
        super().__init__(
            command_prefix=self.config.get('prefix'),
            intents=intents,
            case_insensitive=True,
        )
        self.logger = logger
        self.loaded_cogs = []
        self.unloaded_cogs = []
        self._cog_loader = CogLoader(self)

    async def load_cogs(self) -> None:
        """
        The code in this function is executed whenever the bot starts.
        """
        cogs_path = f"{os.path.realpath(os.path.dirname(__file__))}/cogs"
        for file in os.listdir(cogs_path):
            if file.endswith(".py"):
                extension = file[:-3]
                try:
                    await self.load_extension(f"cogs.{extension}")
                    self.loaded_cogs.append(extension)
                    self.logger.info(f"Loaded extension '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    self.logger.error(
                        f"Failed to load extension {extension}\n{exception}"
                    )
                    self.unloaded_cogs.append(extension)

    async def reload_cog(self, cog_name: str) -> None:
        """Reload a specific cog"""
        await self._cog_loader.reload_cog(cog_name)
        self.logger.info(f"Reloaded cog '{cog_name}'")

    async def unload_cog(self, cog_name: str) -> None:
        """Unload a specific cog"""
        await self._cog_loader.unload_cog(cog_name)
        if cog_name in self.loaded_cogs:
            self.loaded_cogs.remove(cog_name)
            self.unloaded_cogs.append(cog_name)
        self.logger.info(f"Unloaded cog '{cog_name}'")

    async def load_cog(self, cog_name: str) -> None:
        """Load a specific cog"""
        await self._cog_loader.load_cog(cog_name)
        if cog_name in self.unloaded_cogs:
            self.unloaded_cogs.remove(cog_name)
            self.loaded_cogs.append(cog_name)
        self.logger.info(f"Loaded cog '{cog_name}'")

    async def get_loaded_cogs(self) -> list:
        """Get list of currently loaded cogs"""
        return self.loaded_cogs

    async def get_unloaded_cogs(self) -> list:
        """Get list of currently unloaded cogs"""
        return self.unloaded_cogs

    async def setup_hook(self) -> None:
        """This will just be executed when the bot starts the first time."""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info("------")

        # Setup file monitoring
        cogs_path = Path(f"{os.path.realpath(os.path.dirname(__file__))}/cogs")
        self.start_monitoring(cogs_path, CogAutoReload(self), recursive=False)

    async def on_command_error(self, context: Context, error) -> None:
        if isinstance(error, commands.NotOwner):
            embed = discord.Embed(
                description="You are not the owner of the bot!", color=0xE02B2B
            )
            await context.send(embed=embed)
            if context.guild:
                self.logger.warning(
                    f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the guild {context.guild.name} (ID: {context.guild.id}), but the user is not an owner of the bot."
                )
            else:
                self.logger.warning(
                    f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the bot's DMs, but the user is not an owner of the bot."
                )
        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                description="You are missing the permission(s) `"
                + ", ".join(error.missing_permissions)
                + "` to execute this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, UserUnauthorized):
            embed = discord.Embed(
                description="You are not allowed to execute this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, ChannelUnauthorized):
            embed = discord.Embed(
                description="This channel isn't allowed to run this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.BotMissingPermissions):
            embed = discord.Embed(
                description="I am missing the permission(s) `"
                + ", ".join(error.missing_permissions)
                + "` to fully perform this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="Error!",
                description=str(error).capitalize(),
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        else:
            raise error

    async def async_cleanup(self):
        self.logger.info("Cleaning up!")

    async def on_ready(self):
        self.logger.info("Bot is ready!")

        # Load cogs after bot is ready
        if not self.loaded_cogs:  # Only load if not already loaded
            await self.load_cogs()

    async def on_connect(self):
        self.logger.info("Bot connected to Discord!")

    async def on_resume(self):
        self.logger.info("Bot resumed connection!")

    async def on_disconnect(self):
        self.logger.info("Bot disconnected from Discord!")


bot = DiscordBot()


@bot.command()
async def add_channel(ctx, command: str, channel: discord.TextChannel):
    """Add a channel to command permissions."""
    config_manager = ConfigManager()
    channel_id = str(channel.id)

    if config_manager.add_command_channel(command, channel_id):
        await ctx.send(f"Added channel {channel.mention} to command '{command}' permissions")
    else:
        await ctx.send(f"Failed to add channel {channel.mention} to command '{command}' permissions")


@bot.command()
async def remove_channel(ctx, command: str, channel: discord.TextChannel):
    """Remove a channel from command permissions."""
    config_manager = ConfigManager()
    channel_id = str(channel.id)

    if config_manager.remove_command_channel(command, channel_id):
        await ctx.send(f"Removed channel {channel.mention} from command '{command}' permissions")
    else:
        await ctx.send(f"Failed to remove channel {channel.mention} from command '{command}' permissions")


@bot.command()
async def add_user(ctx, command: str, channel: discord.TextChannel, user: discord.Member):
    """Add an authorized user to a command channel."""
    config_manager = ConfigManager()
    channel_id = str(channel.id)
    user_id = str(user.id)

    if config_manager.add_authorized_user(command, channel_id, user_id):
        await ctx.send(f"Added {user.mention} to authorized users for command '{command}' in channel {channel.mention}")
    else:
        await ctx.send(f"Failed to add {user.mention} to authorized users for command '{command}' in channel {channel.mention}")


@bot.command()
async def remove_user(ctx, command: str, channel: discord.TextChannel, user: discord.Member):
    """Remove an authorized user from a command channel."""
    config_manager = ConfigManager()
    channel_id = str(channel.id)
    user_id = str(user.id)

    if config_manager.remove_authorized_user(command, channel_id, user_id):
        await ctx.send(f"Removed {user.mention} from authorized users for command '{command}' in channel {channel.mention}")
    else:
        await ctx.send(f"Failed to remove {user.mention} from authorized users for command '{command}' in channel {channel.mention}")

# Start the bot
bot.run(os.getenv("DISCORD_TOKEN"), log_level=logging.INFO)
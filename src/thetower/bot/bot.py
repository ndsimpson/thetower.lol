# Standard library imports
import datetime
import logging
from datetime import timezone
from os import environ, getenv

import discord

# Third-party imports
import django
from discord.ext import commands
from discord.ext.commands import Context

# Local imports
from thetower.bot.exceptions import ChannelUnauthorized, UserUnauthorized
from thetower.bot.ui.settings_views import SettingsMainView
from thetower.bot.utils import CogManager, ConfigManager, PermissionManager

# Set up logging
log_level = getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))  # Keep basicConfig but modify its formatter
logger = logging.getLogger(__name__)

# Modify the root logger's formatter
formatter = logging.Formatter("%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
formatter.converter = lambda *args: datetime.datetime.now(timezone.utc).timetuple()
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    handler.setFormatter(formatter)

# Prevent discord logs from duplicating
discord_logger = logging.getLogger("discord")
discord_logger.propagate = False

# Discord setup
intents = discord.Intents.default()
intents.presences = True
intents.message_content = True
intents.members = True


class DiscordBot(commands.Bot):
    def __init__(self) -> None:
        environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.towerdb.settings")
        django.setup()
        self.config = ConfigManager()
        self.permission_manager = PermissionManager(self.config)

        super().__init__(
            command_prefix=[],  # Empty list disables text commands (slash commands only)
            intents=intents,
            case_insensitive=True,
            # Add application_id for slash commands support
            application_id=int(getenv("DISCORD_APPLICATION_ID", 0)),
            interaction_timeout=900,  # 15 minutes timeout for slash commands
        )
        self.logger = logger
        self.cog_manager = CogManager(self)

    async def setup_hook(self) -> None:
        """This will just be executed when the bot starts the first time."""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info("------")

        # Add global command check
        self.add_check(self.global_command_check)

        # Note: Global command sync is handled after cogs are loaded in on_ready
        # to ensure all commands are registered before syncing

    async def global_command_check(self, ctx):
        """Global permissions check for all commands."""
        # Always allow the help command
        if ctx.command.name == "help":
            return True

        # Skip checks for cog commands as they have their own check
        if ctx.cog:
            return True

        # Let the permission manager handle the check
        try:
            return await self.permission_manager.check_command_permissions(ctx)
        except (UserUnauthorized, ChannelUnauthorized):
            # Let these exceptions propagate for the error handler
            raise

    async def on_command_error(self, context: Context, error) -> None:
        if isinstance(error, commands.NotOwner):
            embed = discord.Embed(description="You are not the owner of the bot!", color=discord.Color.red())
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
                description="You are missing the permission(s) `" + ", ".join(error.missing_permissions) + "` to execute this command!",
                color=discord.Color.red(),
            )
            await context.send(embed=embed)
        elif isinstance(error, UserUnauthorized):
            embed = discord.Embed(
                description="You are not allowed to execute this command!",
                color=discord.Color.red(),
            )
            await context.send(embed=embed)
        elif isinstance(error, ChannelUnauthorized):
            embed = discord.Embed(
                description="This channel isn't allowed to run this command!",
                color=discord.Color.red(),
            )
            await context.send(embed=embed)

            # Check if the user is the bot owner
            if await self.is_owner(context.author):
                # Use the same logic as BaseCog.get_command_name to get full command path
                cmd = context.command
                parent = cmd.parent
                if parent is None:
                    command_name = cmd.name
                else:
                    command_name = f"{parent.name} {cmd.name}"

                # Get authorized channels from permission manager
                authorized_channels = []

                # Get all command permissions
                command_config = self.permission_manager.get_command_permissions(command_name)
                wildcard_config = self.permission_manager.get_command_permissions("*")

                # Add command-specific authorized channels
                for channel_id, channel_config in command_config.get("channels", {}).items():
                    if channel_id == "*":
                        authorized_channels.append("All channels (wildcard)")
                        continue

                    channel = self.get_channel(int(channel_id))
                    channel_name = f"#{channel.name}" if channel else f"Unknown channel ({channel_id})"

                    # Check if channel is public
                    is_public = channel_config.get("public", False)

                    if is_public:
                        channel_info = f"{channel_name} (Public: anyone can use)"
                    else:
                        # Get authorized users for this channel
                        auth_users = channel_config.get("authorized_users", [])
                        user_mentions = []
                        for user_id in auth_users[:3]:  # Show up to 3 users
                            user = self.get_user(int(user_id))
                            user_mentions.append(f"@{user.name}" if user else f"ID:{user_id}")

                        if len(auth_users) > 3:
                            user_mentions.append(f"+{len(auth_users) - 3} more")

                        users_str = ", ".join(user_mentions) if user_mentions else "None"
                        channel_info = f"{channel_name} (Non-public: {users_str})"

                    authorized_channels.append(channel_info)

                # Add wildcard authorized channels
                for channel_id, channel_config in wildcard_config.get("channels", {}).items():
                    channel = self.get_channel(int(channel_id))
                    channel_name = f"#{channel.name}" if channel else f"Unknown channel ({channel_id})"

                    # Check if this wildcard channel is already in the list (specific permission overrides wildcard)
                    if any(channel_name in ch for ch in authorized_channels):
                        continue

                    # Check if channel is public
                    is_public = channel_config.get("public", False)

                    if is_public:
                        channel_info = f"{channel_name} (via wildcard command, Public)"
                    else:
                        # Get authorized users for this channel
                        auth_users = channel_config.get("authorized_users", [])
                        user_mentions = []
                        for user_id in auth_users[:3]:  # Show up to 3 users
                            user = self.get_user(int(user_id))
                            user_mentions.append(f"@{user.name}" if user else f"ID:{user_id}")

                        if len(auth_users) > 3:
                            user_mentions.append(f"+{len(auth_users) - 3} more")

                        users_str = ", ".join(user_mentions) if user_mentions else "None"
                        channel_info = f"{channel_name} (via wildcard command, Non-public: {users_str})"

                    authorized_channels.append(channel_info)

                # Create and send DM
                dm_embed = discord.Embed(
                    title="Command Permission Error",
                    description=f"Your command `{command_name}` was blocked in {context.channel.mention}",
                    color=discord.Color.orange(),
                )

                if authorized_channels:
                    dm_embed.add_field(name="Allowed Channels", value="\n".join(authorized_channels) or "None", inline=False)
                else:
                    dm_embed.add_field(name="Allowed Channels", value="No channels are authorized for this command", inline=False)

                try:
                    await context.author.send(embed=dm_embed)
                except discord.Forbidden:
                    # Can't send DM to the owner
                    pass
        elif isinstance(error, commands.BotMissingPermissions):
            embed = discord.Embed(
                description="I am missing the permission(s) `" + ", ".join(error.missing_permissions) + "` to fully perform this command!",
                color=discord.Color.red(),
            )
            await context.send(embed=embed)
        else:
            raise error

    async def on_ready(self):
        self.logger.debug("Bot on_ready event triggered")
        self.logger.info("Bot is ready!")

        # Load cogs after bot is ready
        if not self.cog_manager.loaded_cogs:  # Only load if not already loaded
            self.logger.debug("Loading cogs...")
            await self.cog_manager.load_cogs()
            self.logger.debug(f"Loaded cogs: {self.cog_manager.loaded_cogs}")

            # Sync all commands globally after cogs are loaded
            self.logger.info("Syncing all slash commands globally...")
            try:
                # Log commands being synced
                commands = [cmd.name for cmd in self.tree.get_commands()]
                self.logger.info(f"Syncing {len(commands)} slash commands globally: {', '.join(commands)}")

                await self.tree.sync()
                self.logger.info("Global command sync complete")
            except Exception as e:
                self.logger.error(f"Failed to sync commands globally: {e}")

    async def on_connect(self):
        self.logger.info("Bot connected to Discord!")

    async def on_resume(self):
        self.logger.info("Bot resumed connection!")

    async def on_disconnect(self):
        self.logger.info("Bot disconnected from Discord!")


bot = DiscordBot()


# ============================================================================
# Global Error Handler
# ============================================================================


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Global error handler for application commands."""
    from thetower.bot.exceptions import CogNotEnabled

    # Handle CheckFailure from permission checks
    if isinstance(error, discord.app_commands.CheckFailure):
        # Check if interaction was already responded to (e.g., by basecog checks)
        if interaction.response.is_done():
            return

        # Check if the original exception was CogNotEnabled
        original = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
        if isinstance(original, CogNotEnabled):
            await interaction.response.send_message(
                f"❌ **{original.cog_name}** is not enabled for this server.\n\n"
                f"This feature must be enabled by your server owner before it can be used.\n"
                f"💡 **To enable:** Ask your server administrator to run `/settings`, "
                f"navigate to **Manage Cogs**, and enable **{original.cog_name}**.",
                ephemeral=True,
            )
            return

        # Check if this is a channel authorization failure
        error_str = str(error)
        if "unauthorized channel" in error_str.lower() or "channel authorization" in error_str.lower():
            await interaction.response.send_message(
                "❌ This command cannot be used in this channel. Please use an authorized channel or contact an administrator.", ephemeral=True
            )
        else:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    # Log other errors
    logger.error(f"Error in command '{interaction.command.name if interaction.command else 'unknown'}': {error}", exc_info=error)

    # Try to send error message to user
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ An error occurred: {error}", ephemeral=True)
    except Exception:
        pass  # Interaction may have expired


# ============================================================================
# Slash Commands
# ============================================================================


@bot.tree.command(name="sync_commands", description="Manually sync slash commands for this guild")
async def sync_commands_slash(interaction: discord.Interaction):
    """Manually sync slash commands for this guild.

    This command is useful if slash commands are not appearing in Discord.
    Only server owners or the bot owner can use this command.
    """
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    # Check if user has permission (guild owner or bot owner)
    is_bot_owner = await bot.is_owner(interaction.user)
    is_guild_owner = interaction.user.id == interaction.guild.owner_id

    if not (is_bot_owner or is_guild_owner):
        await interaction.response.send_message("❌ Only the server owner or bot owner can sync commands.", ephemeral=True)
        return

    try:
        await interaction.response.defer(ephemeral=True)

        # Log commands being synced
        commands = [cmd.name for cmd in bot.tree.get_commands()]
        logger.info(f"Syncing {len(commands)} slash commands for guild {interaction.guild.id} ({interaction.guild.name}): {', '.join(commands)}")

        await bot.tree.sync(guild=interaction.guild)
        await interaction.followup.send("✅ Slash commands synced successfully!", ephemeral=True)
        logger.info(f"Successfully synced slash commands for guild {interaction.guild.id} ({interaction.guild.name})")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands: {e}", ephemeral=True)
        logger.error(f"Failed to manually sync commands for guild {interaction.guild.id}: {e}")


@bot.tree.command(name="settings", description="Open the bot settings interface")
async def settings_slash(interaction: discord.Interaction):
    """Open the interactive settings interface."""
    # Defer the response to prevent timeout during permission checks
    await interaction.response.defer(ephemeral=True)

    is_bot_owner = await bot.is_owner(interaction.user)
    guild_id = interaction.guild.id if interaction.guild else None

    # Check if user has permission
    if not is_bot_owner:
        if not interaction.guild:
            return await interaction.followup.send("❌ Settings can only be accessed in a server (unless you're the bot owner).", ephemeral=True)
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.followup.send("❌ Only the server owner or bot owner can access settings.", ephemeral=True)

    # Create main settings view
    view = SettingsMainView(is_bot_owner, guild_id)

    embed = discord.Embed(title="⚙️ Settings", description="Select a category to manage", color=discord.Color.blue())

    if is_bot_owner:
        embed.add_field(name="👑 Bot Owner", value="You have full access to all settings", inline=False)

    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


def main():
    """Main entry point for the Discord bot."""
    bot.run(getenv("DISCORD_TOKEN"), log_level=logging.INFO)


# Bot instance is available for import
__all__ = ["bot", "DiscordBot", "main"]

# Run bot if this module is executed directly
if __name__ == "__main__":
    main()

# Standard library imports
import logging
from os import environ, getenv
from pathlib import Path

# Third-party imports
import django
import discord
from discord.ext import commands
from discord.ext.commands import Context

# Local imports
from fish_bot.exceptions import UserUnauthorized, ChannelUnauthorized
from fish_bot.utils import BaseFileMonitor, ConfigManager, CogAutoReload, CogManager, MemoryUtils

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
        environ.setdefault("DJANGO_SETTINGS_MODULE", "dtower.thetower.settings")
        django.setup()
        self.config = ConfigManager()
        super().__init__(
            command_prefix=self.config.get('prefix'),
            intents=intents,
            case_insensitive=True,
        )
        self.logger = logger
        self.cog_manager = CogManager(self)

    async def setup_hook(self) -> None:
        """This will just be executed when the bot starts the first time."""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info("------")

        # Setup file monitoring
        cogs_path = Path(__file__).parent.resolve() / "cogs"
        self.start_monitoring(cogs_path, CogAutoReload(self), recursive=False)

        # Add global command check
        self.add_check(self.global_command_check)

    async def global_command_check(self, ctx):
        """Global permissions check for all commands."""
        # Always allow the help command
        if ctx.command.name == 'help':
            return True

        # Skip checks for cog commands as they have their own check
        if ctx.cog:
            return True

        # Always allow DMs from bot owner
        if ctx.guild is None and await self.is_owner(ctx.author):
            # self.logger.info(f"Bot owner {ctx.author} (ID: {ctx.author.id}) used command '{ctx.command.name}' in DM")
            return True

        permissions = self.config.get("command_permissions", {"commands": {}})

        # Check for wildcard command permission
        wildcard_config = permissions["commands"].get("*", {})
        if str(ctx.channel.id) in wildcard_config.get("channels", {}):
            return True

        command_name = ctx.command.name
        command_config = permissions["commands"].get(command_name, {})
        channel_config = command_config.get("channels", {}).get(str(ctx.channel.id))

        # Check for wildcard channel permission
        if "*" in command_config.get("channels", {}):
            return True

        # Check channel permissions
        if not channel_config:
            self.logger.warning(
                f"Command '{command_name}' blocked - unauthorized channel. "
                f"Channel: {ctx.channel} (ID: {ctx.channel.id})"
            )
            raise ChannelUnauthorized(ctx.channel)

        # Check user permissions if channel is not public
        if not channel_config.get("public", False):
            if str(ctx.author.id) not in channel_config.get("authorized_users", []):
                self.logger.warning(
                    f"Command '{command_name}' blocked - unauthorized user. "
                    f"User: {ctx.author} (ID: {ctx.author.id})"
                )
                raise UserUnauthorized(ctx.author)

        return True

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

            # Check if the user is the bot owner
            if await self.is_owner(context.author):
                command_name = context.command.name
                permissions = self.config.get("command_permissions", {"commands": {}})

                # Get command permissions
                command_config = permissions["commands"].get(command_name, {})
                wildcard_config = permissions["commands"].get("*", {})

                # Create detailed permissions message for bot owner
                authorized_channels = []

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
                    color=discord.Color.orange()
                )

                if authorized_channels:
                    dm_embed.add_field(
                        name="Allowed Channels",
                        value="\n".join(authorized_channels) or "None",
                        inline=False
                    )
                else:
                    dm_embed.add_field(
                        name="Allowed Channels",
                        value="No channels are authorized for this command",
                        inline=False
                    )

                try:
                    await context.author.send(embed=dm_embed)
                except discord.Forbidden:
                    # Can't send DM to the owner
                    pass
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
        if not self.cog_manager.loaded_cogs:  # Only load if not already loaded
            await self.cog_manager.load_cogs()

    async def on_connect(self):
        self.logger.info("Bot connected to Discord!")

    async def on_resume(self):
        self.logger.info("Bot resumed connection!")

    async def on_disconnect(self):
        self.logger.info("Bot disconnected from Discord!")


bot = DiscordBot()


@bot.command()
async def enable_cog(ctx, cog_name: str):
    """Enable a cog by adding it to enabled_cogs list."""
    await bot.cog_manager.enable_cog_with_ctx(ctx, cog_name)


@bot.command()
async def disable_cog(ctx, cog_name: str):
    """Disable a cog by adding it to disabled_cogs list."""
    await bot.cog_manager.disable_cog_with_ctx(ctx, cog_name)


@bot.command()
async def toggle_load_all(ctx):
    """Toggle the load_all_cogs setting."""
    new_setting = await bot.cog_manager.toggle_load_all()
    status = "enabled" if new_setting else "disabled"
    await ctx.send(f"🔄 Load all cogs setting is now {status}.")


@bot.command()
async def list_cogs(ctx):
    """List all available cogs and their status."""
    await bot.cog_manager.list_modules(ctx)


@bot.command()
async def add_channel(ctx, command: str, channel_input):
    """Add a channel to command permissions.

    Parameters:
    -----------
    command: The name of the command to authorize in the channel
    channel_input: The Discord channel to grant permission to (mention, name, or ID)

    Examples:
    ---------
    $add_channel list_cogs #bot-commands
    $add_channel * #admin-channel    (allows all commands in admin-channel)
    $add_channel list_cogs bot-commands
    $add_channel * 1234567890123456789
    """
    # Handle different channel input types
    channel = None

    # Check if it's a channel mention
    if len(ctx.message.channel_mentions) > 0:
        channel = ctx.message.channel_mentions[0]
    else:
        # Try to interpret as a channel ID
        try:
            channel_id = int(channel_input)
            channel = ctx.guild.get_channel(channel_id)
        except (ValueError, TypeError):
            # Try to interpret as a channel name
            channel = discord.utils.get(ctx.guild.text_channels, name=channel_input)

    # If we couldn't find a channel, inform the user
    if not channel:
        await ctx.send(f"Could not find channel '{channel_input}'. Please provide a valid channel mention, name, or ID.")
        return

    channel_id = str(channel.id)

    if bot.config.add_command_channel(command, channel_id):
        await ctx.send(f"Added channel {channel.mention} to command '{command}' permissions")
    else:
        await ctx.send(f"Failed to add channel {channel.mention} to command '{command}' permissions")


@bot.command()
async def remove_channel(ctx, command: str, channel_input):
    """Remove a channel from command permissions.

    Parameters:
    -----------
    command: The name of the command to remove permission for
    channel_input: The Discord channel to remove permission from (mention, name, or ID)

    Examples:
    ---------
    $remove_channel list_cogs #bot-commands
    $remove_channel * #admin-channel
    $remove_channel list_cogs bot-commands
    $remove_channel * 1234567890123456789
    """
    # Handle different channel input types
    channel = None

    # Check if it's a channel mention
    if len(ctx.message.channel_mentions) > 0:
        channel = ctx.message.channel_mentions[0]
    else:
        # Try to interpret as a channel ID
        try:
            channel_id = int(channel_input)
            channel = ctx.guild.get_channel(channel_id)
        except (ValueError, TypeError):
            # Try to interpret as a channel name
            channel = discord.utils.get(ctx.guild.text_channels, name=channel_input)

    # If we couldn't find a channel, inform the user
    if not channel:
        await ctx.send(f"Could not find channel '{channel_input}'. Please provide a valid channel mention, name, or ID.")
        return

    channel_id = str(channel.id)

    if bot.config.remove_command_channel(command, channel_id):
        await ctx.send(f"Removed channel {channel.mention} from command '{command}' permissions")
    else:
        await ctx.send(f"Failed to remove channel {channel.mention} from command '{command}' permissions")


@bot.command()
async def add_user(ctx, command: str, channel: discord.TextChannel, user: discord.Member):
    """Add an authorized user to a command channel."""
    channel_id = str(channel.id)
    user_id = str(user.id)

    if bot.config.add_authorized_user(command, channel_id, user_id):
        await ctx.send(f"Added {user.mention} to authorized users for command '{command}' in channel {channel.mention}")
    else:
        await ctx.send(f"Failed to add {user.mention} to authorized users for command '{command}' in channel {channel.mention}")


@bot.command()
async def remove_user(ctx, command: str, channel: discord.TextChannel, user: discord.Member):
    """Remove an authorized user from a command channel."""
    channel_id = str(channel.id)
    user_id = str(user.id)

    if bot.config.remove_authorized_user(command, channel_id, user_id):
        await ctx.send(f"Removed {user.mention} from authorized users for command '{command}' in channel {channel.mention}")
    else:
        await ctx.send(f"Failed to remove {user.mention} from authorized users for command '{command}' in channel {channel.mention}")


@bot.command()
async def reload_cog(ctx, cog_name: str):
    """Reload a specific cog."""
    await bot.cog_manager.reload_cog_with_ctx(ctx, cog_name)


@bot.command()
async def reload_all_cogs(ctx):
    """Reload all currently loaded cogs."""
    await ctx.send("🔄 Reloading all cogs...")

    loaded_cogs = list(bot.cogs.keys())
    total_cogs = len(loaded_cogs)

    if total_cogs == 0:
        return await ctx.send("⚠️ No cogs are currently loaded.")

    # Progress message
    progress_msg = await ctx.send(f"Beginning reload of {total_cogs} cogs...")

    # Track results
    success_count = 0
    failed_cogs = []

    # Attempt to reload each cog
    for cog_name in loaded_cogs:
        try:
            success = await bot.cog_manager.reload_cog(cog_name)
            if success:
                success_count += 1
            else:
                failed_cogs.append(f"{cog_name} (unknown error)")
        except Exception as e:
            bot.logger.error(f"Failed to reload cog {cog_name}: {str(e)}")
            failed_cogs.append(f"{cog_name} ({str(e)[:50]}{'...' if len(str(e)) > 50 else ''})")

    # Create result embed
    embed = discord.Embed(
        title="Cog Reload Results",
        color=discord.Color.green() if not failed_cogs else discord.Color.orange()
    )

    embed.add_field(
        name="Summary",
        value=f"✅ Successfully reloaded: {success_count}/{total_cogs}",
        inline=False
    )

    if failed_cogs:
        embed.add_field(
            name="❌ Failed to reload",
            value="\n".join(failed_cogs) or "None",
            inline=False
        )

    await progress_msg.delete()
    await ctx.send(embed=embed)


@bot.group(name="memory", aliases=["mem"], invoke_without_command=True)
async def memory_group(ctx):
    """Commands for checking memory usage"""
    if ctx.invoked_subcommand is None:
        await MemoryUtils.send_memory_report(ctx, ctx.bot, "Bot Memory Usage")


@memory_group.command(name="detailed")
async def memory_detailed(ctx):
    """Get detailed memory usage for the entire bot"""
    await ctx.send("Analyzing detailed memory usage... this may take a moment.")
    await MemoryUtils.send_memory_report(ctx, ctx.bot, "Detailed Bot Memory Usage", detailed=True)


@memory_group.command(name="cog")
async def memory_cog(ctx, cog_name: str):
    """Get memory usage for a specific cog"""
    cog = ctx.bot.get_cog(cog_name)
    if not cog:
        return await ctx.send(f"Cog '{cog_name}' not found")

    await MemoryUtils.send_memory_report(ctx, cog, f"{cog_name} Memory Usage")


@memory_group.command(name="cogs")
async def memory_all_cogs(ctx):
    """Get memory usage breakdown for all cogs"""
    from pympler import asizeof

    # Measure all cogs
    cog_sizes = {}
    for cog_name, cog in ctx.bot.cogs.items():
        cog_sizes[cog_name] = asizeof.asizeof(cog)

    # Create embed
    embed = discord.Embed(
        title="Cog Memory Usage",
        color=discord.Color.blue()
    )

    # Calculate total size
    total_size = sum(cog_sizes.values())
    embed.add_field(
        name="Total Cogs Size",
        value=MemoryUtils.format_bytes(total_size),
        inline=False
    )

    # Sort cogs by size and create the breakdown text
    cog_size_text = "\n".join([
        f"**{name}**: {MemoryUtils.format_bytes(size)}"
        for name, size in sorted(cog_sizes.items(), key=lambda x: x[1], reverse=True)
    ])

    embed.add_field(
        name="Size by Cog",
        value=cog_size_text or "No cogs found",
        inline=False
    )

    await ctx.send(embed=embed)


# Start the bot
bot.run(getenv("DISCORD_TOKEN"), log_level=logging.INFO)
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
from thetower.bot.utils import BaseFileMonitor, CogManager, CommandTypeManager, ConfigManager, MemoryUtils, PermissionManager

# Set up logging
log_level = getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

# Discord setup
intents = discord.Intents.default()
intents.presences = True
intents.message_content = True
intents.members = True


class DiscordBot(commands.Bot, BaseFileMonitor):
    def __init__(self) -> None:
        environ.setdefault("DJANGO_SETTINGS_MODULE", "thetower.backend.settings")
        django.setup()
        self.config = ConfigManager()
        self.permission_manager = PermissionManager(self.config)

        # Initialize default command type settings if they don't exist
        if not self.config.get("command_type_mode", None):
            self.config.config["command_type_mode"] = "prefix"  # Default to prefix type
            self.config.save_config()

        super().__init__(
            command_prefix=self.config.get("prefix"),
            intents=intents,
            case_insensitive=True,
            # Add application_id for slash commands support
            application_id=int(getenv("DISCORD_APPLICATION_ID", 0)),
            interaction_timeout=900,  # 15 minutes timeout for slash commands
        )
        self.logger = logger
        self.cog_manager = CogManager(self)

        # Store command types configuration
        self.command_types = self.config.get("command_types", {})

        # Set up logging with UTC timestamps
        formatter = logging.Formatter("%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        formatter.converter = lambda *args: datetime.datetime.now(timezone.utc).timetuple()

        # Configure the root logger
        root_logger = logging.getLogger("thetower.bot")
        if not root_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)

    async def setup_hook(self) -> None:
        """This will just be executed when the bot starts the first time."""
        self.logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info("------")

        # Setup file monitoring through CogManager instead of directly
        self.cog_manager.start_observer()

        # Add global command check
        self.add_check(self.global_command_check)

        # Set up command type handling
        self.command_type_manager = CommandTypeManager(self)

        # Auto-sync slash commands if enabled
        if self.config.get("auto_sync_commands", True):
            self.logger.info("Auto-syncing commands with Discord...")
            try:
                await self.tree.sync()
                self.logger.info("Command sync complete")
            except Exception as e:
                self.logger.error(f"Failed to sync commands: {e}")

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
        elif isinstance(error, commands.CommandNotFound):
            # Log the unknown command attempt
            command_name = (
                context.message.content.split()[0][len(context.prefix) :] if context.message.content.startswith(context.prefix) else "Unknown"
            )
            self.logger.info(f"Unknown command '{command_name}' attempted by {context.author} (ID: {context.author.id})")

            # Check if we should log to a Discord channel
            error_channel_id = self.config.get("error_log_channel", None)
            if error_channel_id:
                try:
                    channel = self.get_channel(int(error_channel_id))
                    if channel:
                        # Create informative embed for the error log channel
                        embed = discord.Embed(
                            title="Command Not Found",
                            description="Unknown command attempted",
                            color=discord.Color.orange(),
                            timestamp=context.message.created_at,
                        )

                        # Add details about the command attempt
                        embed.add_field(name="Attempted Command", value=f"`{context.message.content}`", inline=False)
                        embed.add_field(name="User", value=f"{context.author.mention} ({context.author})", inline=True)
                        embed.add_field(name="User ID", value=f"`{context.author.id}`", inline=True)

                        # Add location details
                        if context.guild:
                            embed.add_field(name="Server", value=context.guild.name, inline=True)
                            embed.add_field(name="Channel", value=f"{context.channel.mention}", inline=True)
                        else:
                            embed.add_field(name="Location", value="Direct Message", inline=True)

                        await channel.send(embed=embed)
                except Exception as e:
                    self.logger.error(f"Failed to log CommandNotFound to Discord channel: {e}")
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
        elif isinstance(error, commands.MissingRequiredArgument):
            # Get command signature and clean it up for display
            signature = context.command.signature

            # Create a more informative error message with command usage
            command_name = context.command.qualified_name
            prefix = context.prefix
            usage = f"{prefix}{command_name} {signature}"

            # Highlight the missing parameter in the error description
            param_name = error.param.name
            error_message = f"The argument `{param_name}` is required but was not provided."

            embed = discord.Embed(
                title="Missing Required Argument", description=f"{error_message}\n\n**Usage:**\n`{usage}`", color=discord.Color.red()
            )

            # If there's a command help text, include it
            if context.command.help:
                # Extract the first paragraph of help (stops at first double newline)
                help_text = context.command.help.split("\n\n")[0].strip()
                embed.add_field(name="Help", value=help_text, inline=False)

            # Add examples if they exist in the help text
            if context.command.help and "Examples:" in context.command.help:
                examples_section = context.command.help.split("Examples:")[1].strip()
                # Get only the example section, stopping at the next major section if it exists
                if "\n\n" in examples_section:
                    examples_section = examples_section.split("\n\n")[0].strip()
                embed.add_field(name="Examples", value=examples_section, inline=False)

            await context.send(embed=embed)
        else:
            raise error

    async def async_cleanup(self):
        self.logger.info("Cleaning up!")

    async def on_ready(self):
        self.logger.debug("Bot on_ready event triggered")
        self.logger.info("Bot is ready!")

        # Load cogs after bot is ready
        if not self.cog_manager.loaded_cogs:  # Only load if not already loaded
            self.logger.debug("Loading cogs...")
            await self.cog_manager.load_cogs()
            self.logger.debug(f"Loaded cogs: {self.cog_manager.loaded_cogs}")

    async def on_connect(self):
        self.logger.info("Bot connected to Discord!")

    async def on_resume(self):
        self.logger.info("Bot resumed connection!")

    async def on_disconnect(self):
        self.logger.info("Bot disconnected from Discord!")


bot = DiscordBot()


@bot.group(name="cog", aliases=["cogs"], invoke_without_command=True)
async def cog_group(ctx):
    """Commands for managing bot cogs/modules"""
    if ctx.invoked_subcommand is None:
        await bot.cog_manager.list_modules(ctx)


@cog_group.command(name="enable")
async def cog_enable(ctx, cog_name: str):
    """Enable a cog by adding it to enabled_cogs list.

    Args:
        cog_name: Name of the cog to enable
    """
    await bot.cog_manager.enable_cog_with_ctx(ctx, cog_name)


@cog_group.command(name="disable")
async def cog_disable(ctx, cog_name: str):
    """Disable a cog by adding it to disabled_cogs list.

    Args:
        cog_name: Name of the cog to disable
    """
    await bot.cog_manager.disable_cog_with_ctx(ctx, cog_name)


@cog_group.command(name="list")
async def cog_list(ctx):
    """List all available cogs and their status."""
    await bot.cog_manager.list_modules(ctx)


@cog_group.command(name="load")
async def cog_load(ctx, cog_name: str):
    """Load a specific cog.

    Args:
        cog_name: Name of the cog to load

    Examples:
        $cog load music       (loads the music cog)
        $cog load admin       (loads the admin cog)
    """
    await bot.cog_manager.load_cog_with_ctx(ctx, cog_name)


@cog_group.command(name="unload")
async def cog_unload(ctx, cog_name: str):
    """Unload a specific cog.

    Args:
        cog_name: Name of the cog to unload

    Examples:
        $cog unload music     (unloads the music cog)
        $cog unload admin     (unloads the admin cog)
    """
    await bot.cog_manager.unload_cog_with_ctx(ctx, cog_name)


@cog_group.command(name="reload")
async def cog_reload(ctx, cog_name: str):
    """Reload a specific cog.

    Args:
        cog_name: Name of the cog to reload
    """
    await bot.cog_manager.reload_cog_with_ctx(ctx, cog_name)


@cog_group.command(name="reload_all")
async def cog_reload_all(ctx):
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
    embed = discord.Embed(title="Cog Reload Results", color=discord.Color.green() if not failed_cogs else discord.Color.orange())

    embed.add_field(name="Summary", value=f"✅ Successfully reloaded: {success_count}/{total_cogs}", inline=False)

    if failed_cogs:
        embed.add_field(name="❌ Failed to reload", value="\n".join(failed_cogs) or "None", inline=False)

    await progress_msg.delete()
    await ctx.send(embed=embed)


@cog_group.group(name="autoreload", aliases=["auto"], invoke_without_command=True)
async def cog_autoreload_group(ctx):
    """Auto-reload settings for cogs"""
    if ctx.invoked_subcommand is None:
        await bot.cog_manager.auto_reload_settings(ctx)


@cog_group.command(name="toggle")
async def cog_toggle(ctx, setting_name: str, value: bool = None):
    """Toggle a cog-related setting.

    Args:
        setting_name: Name of the setting to toggle (load_all, auto_reload)
        value: Optional boolean value to set explicitly. If omitted, toggles current value.

    Examples:
        $cog toggle load_all        (toggle the load_all_cogs setting)
        $cog toggle load_all True   (explicitly enable load_all_cogs)
        $cog toggle auto_reload     (toggle auto-reload for all cogs)
    """
    setting_name = setting_name.lower()

    # Handle load_all_cogs setting
    if setting_name in ["load_all", "load_all_cogs"]:
        current_value = bot.config.get("load_all_cogs", False)
        new_value = not current_value if value is None else value
        bot.config.config["load_all_cogs"] = new_value
        bot.config.save_config()
        status = "✅ Enabled" if new_value else "❌ Disabled"
        await ctx.send(f"Setting `load_all_cogs` is now {status}")
        return

    # Handle auto_reload setting
    elif setting_name in ["auto_reload", "auto", "autoreload"]:
        await bot.cog_manager.toggle_auto_reload_with_ctx(ctx)
        return

    # Handle per-cog auto_reload setting
    elif setting_name.startswith("auto_reload_"):
        cog_name = setting_name[len("auto_reload_") :]
        if not cog_name:
            await ctx.send("❌ Please specify a cog name: `auto_reload_cogname`")
            return

        await ctx.invoke(bot.get_command("cog autoreload toggle_cog"), cog_name=cog_name)
        return

    # Unknown setting
    await ctx.send(f"❌ Unknown setting: `{setting_name}`\nValid settings: `load_all`, `auto_reload`, `auto_reload_cogname`")


@cog_group.command(name="pause")
async def cog_pause(ctx, value: bool = None):
    """Pause or unpause the cog auto-reload system.

    When paused, file changes won't trigger automatic reloads.

    Args:
        value: Optional boolean value to set explicitly.
              If omitted, toggles the current state.

    Examples:
        $cog pause          (toggle pause state)
        $cog pause True     (explicitly pause)
        $cog pause False    (explicitly unpause)
    """
    # Get current observer status
    is_paused = not bot.cog_manager.observer_running

    # Determine new value (toggle if not specified)
    new_paused_state = not is_paused if value is None else value

    # Apply the change
    if new_paused_state:
        if bot.cog_manager.observer_running:
            bot.cog_manager.stop_observer()
            await ctx.send("System is now ⏸️ Paused (auto-reload disabled)")
        else:
            await ctx.send("System is already ⏸️ Paused")
    else:
        if not bot.cog_manager.observer_running:
            bot.cog_manager.start_observer()
            await ctx.send("System is now ✅ Running (auto-reload enabled)")
        else:
            await ctx.send("System is already ✅ Running")


# Keep the specialized toggle_cog command in the autoreload subgroup since it requires special handling
@cog_autoreload_group.command(name="toggle_cog")
async def cog_autoreload_toggle_cog(ctx, cog_name: str):
    """Toggle auto-reload for a specific cog.

    Args:
        cog_name: The name of the cog to toggle auto-reload for

    Examples:
        $cog autoreload toggle_cog music
        $cog autoreload toggle_cog utils
    """
    await bot.cog_manager.toggle_cog_auto_reload_with_ctx(ctx, cog_name)


@cog_group.command(name="toggle_autostart")
async def cog_toggle_autostart(ctx, cog_name: str):
    """Toggle autostart for a cog.

    Args:
        cog_name: The cog to toggle autostart for

    Examples:
        $cog toggle_autostart service_control
    """
    await bot.cog_manager.toggle_cog_autostart_with_ctx(ctx, cog_name)


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
    embed = discord.Embed(title="Cog Memory Usage", color=discord.Color.blue())

    # Calculate total size
    total_size = sum(cog_sizes.values())
    embed.add_field(name="Total Cogs Size", value=MemoryUtils.format_bytes(total_size), inline=False)

    # Sort cogs by size and create the breakdown text
    cog_size_text = "\n".join(
        [f"**{name}**: {MemoryUtils.format_bytes(size)}" for name, size in sorted(cog_sizes.items(), key=lambda x: x[1], reverse=True)]
    )

    embed.add_field(name="Size by Cog", value=cog_size_text or "No cogs found", inline=False)

    await ctx.send(embed=embed)


@bot.group(name="perm", aliases=["perms", "permission", "permissions"], invoke_without_command=True)
async def permission_group(ctx):
    """Command group for managing command permissions"""
    if ctx.invoked_subcommand is None:
        await bot.permission_manager.show_permissions_overview(ctx)


@permission_group.command(name="list")
async def permission_list(ctx, command_name: str = None):
    """List permissions for a specific command or all commands"""
    await bot.permission_manager.show_permissions(ctx, command_name)


@permission_group.command(name="add_channel", aliases=["ac"])
async def permission_add_channel(ctx, command: str, channel_input: str, public: bool = False):
    """Add a channel to command permissions."""
    success, message = await bot.permission_manager.cmd_add_channel(ctx, command, channel_input, public)
    if success:
        await ctx.send(message)
    else:
        await ctx.send(f"❌ {message}")


@permission_group.command(name="remove_channel", aliases=["rc"])
async def permission_remove_channel(ctx, command: str, channel_input: str):
    """Remove a channel from command permissions.

    Args:
        command: The command name
        channel_input: Channel mention, ID, name, or search term
    """
    channel = await bot.permission_manager.resolve_channel_from_input(ctx, channel_input)
    if not channel:
        await ctx.send(f"❌ Could not find channel matching '{channel_input}'")
        return

    if await bot.permission_manager.cmd_remove_channel(ctx, command, channel_input):
        await ctx.send(f"✅ Removed {channel.mention} from allowed channels for command `{command}`")
    else:
        await ctx.send(f"❌ Failed to remove channel permissions for command `{command}`")


@permission_group.command(name="add_user", aliases=["au"])
async def permission_add_user(ctx, command: str, channel_input: str, user: discord.Member):
    """Add a user to authorized users for a command in a channel."""
    channel = await PermissionManager.resolve_channel_from_input(ctx, channel_input)
    if not channel:
        await ctx.send("Could not find that channel.")
        return

    if await ctx.bot.permission_manager.cmd_add_user(ctx, command, channel.id, user):
        await ctx.send(f"Added {user.mention} to authorized users for '{command}' in {channel.mention}")
    else:
        await ctx.send("Failed to add user permissions")


@permission_group.command(name="remove_user", aliases=["ru"])
async def permission_remove_user(ctx, command: str, channel_input: str, user: discord.Member):
    """Remove a user from authorized users for a command in a channel."""
    channel = await PermissionManager.resolve_channel_from_input(ctx, channel_input)
    if not channel:
        await ctx.send("Could not find that channel.")
        return

    if await ctx.bot.permission_manager.cmd_remove_user(ctx, command, channel.id, user):
        await ctx.send(f"Removed {user.mention} from authorized users for '{command}' in {channel.mention}")
    else:
        await ctx.send("Failed to remove user permissions")


@permission_group.command(name="set_public")
async def permission_set_public(ctx, command: str, channel_input, public: bool = True):
    """Set whether a command is public in a channel

    Examples:
    ---------
    !perm set_public list_cogs #bot-commands true    (make public)
    !perm set_public list_cogs #bot-commands false   (make non-public)
    """
    channel = await bot.permission_manager.resolve_channel_from_input(ctx, channel_input)
    if not channel:
        return await ctx.send(f"Could not find channel '{channel_input}'")

    success = bot.permission_manager.set_channel_public(command, str(channel.id), public)
    if success:
        status = "public" if public else "non-public"
        await ctx.send(f"✅ Set command '{command}' to {status} in {channel.mention}")
    else:
        await ctx.send("❌ Failed to update permission settings")


@permission_group.command(name="reload")
async def permission_reload(ctx):
    """Reload permissions from configuration file"""
    bot.permission_manager.reload_permissions()
    await ctx.send("✅ Permission settings reloaded from configuration")


@permission_group.command(name="alias_info", aliases=["aliases"])
async def permission_alias_info(ctx, command_name: str = None):
    """Show command alias mappings and permission details.

    Args:
        command_name: Optional command to check specifically
    """
    try:
        # This command requires special permissions - only for admins
        embed = discord.Embed(title="Command Alias Mappings", description="How command aliases map to primary commands", color=discord.Color.blue())

        if command_name:
            # Check a specific command
            cmd = bot.get_command(command_name)
            if not cmd:
                await ctx.send(f"❌ Command '{command_name}' not found.")
                return

            # Get the primary name
            primary_name = cmd.name
            aliases = cmd.aliases

            embed.title = f"Command: {primary_name}"

            # Show alias information
            if aliases:
                embed.add_field(name="Aliases", value="\n".join([f"`{alias}` → `{primary_name}`" for alias in aliases]), inline=False)
            else:
                embed.add_field(name="Aliases", value="No aliases", inline=False)

            # Show permission information
            permissions = bot.permission_manager.get_command_permissions(primary_name)

            if permissions and "channels" in permissions:
                channel_info = []

                for channel_id, perms in permissions["channels"].items():
                    channel_name = channel_id
                    if channel_id != "*":
                        channel = bot.get_channel(int(channel_id))
                        channel_name = f"#{channel.name}" if channel else channel_id
                    else:
                        channel_name = "All Channels"

                    is_public = perms.get("public", False)
                    status = "✅ Public" if is_public else "🔒 Restricted"

                    if not is_public:
                        user_count = len(perms.get("authorized_users", []))
                        status += f" ({user_count} authorized users)"

                    channel_info.append(f"{channel_name}: {status}")

                if channel_info:
                    embed.add_field(name="Authorized Channels", value="\n".join(channel_info), inline=False)
                else:
                    embed.add_field(name="Authorized Channels", value="No channels authorized", inline=False)
            else:
                embed.add_field(name="Permissions", value="No specific permissions set", inline=False)
        else:
            # Show commands with aliases
            commands_with_aliases = [(cmd.name, cmd.aliases) for cmd in bot.commands if cmd.aliases]

            if not commands_with_aliases:
                embed.add_field(name="No Aliases", value="No commands have aliases configured", inline=False)
            else:
                # Sort alphabetically for consistency
                for name, aliases in sorted(commands_with_aliases):
                    embed.add_field(name=f"Command: {name}", value="\n".join([f"`{alias}` → `{name}`" for alias in aliases]), inline=True)

        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error in alias_info command: {e}", exc_info=True)
        await ctx.send(f"❌ Error processing command: {e}")


@permission_group.command(name="toggle")
async def permission_toggle(ctx, setting_name: str, value: bool = None):
    """Toggle a permission-related setting.

    Args:
        setting_name: Name of the setting to toggle
        value: Optional boolean value to set explicitly. If omitted, toggles current value.

    Examples:
        $perm toggle owner_bypass       (toggle whether bot owners bypass all permission checks)
        $perm toggle strict_channel     (toggle strict channel permission enforcement)
    """
    setting_name = setting_name.lower()
    valid_settings = ["owner_bypass", "strict_channel", "log_denied"]  # Add permission-specific settings

    if setting_name not in valid_settings:
        return await ctx.send(f"❌ Unknown setting: `{setting_name}`\nValid settings: {', '.join([f'`{s}`' for s in valid_settings])}")

    # Get current value from permission manager config
    setting_key = f"permission_{setting_name}"  # Use consistent prefix for permission settings
    current_value = bot.config.get(setting_key, False)

    # Determine new value (toggle if not specified)
    new_value = not current_value if value is None else value

    # Update the setting
    bot.config.config[setting_key] = new_value
    bot.config.save_config()

    # Reload permission manager to apply changes
    bot.permission_manager.reload_permissions()

    # Report the new state
    status = "✅ Enabled" if new_value else "❌ Disabled"
    await ctx.send(f"Permission setting `{setting_name}` is now {status}")


@bot.command()
async def settings(ctx):
    """Display all bot-level settings and configuration."""
    # Create the main settings embed following standardized embed structure
    embed = discord.Embed(title="Bot Settings", description="Current configuration for bot system", color=discord.Color.blue())

    # Get basic bot configuration
    prefix = bot.config.get("prefix", "$")
    error_channel_id = bot.config.get("error_log_channel", None)
    error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

    # General settings section
    general_settings = [f"**Prefix**: `{prefix}`", f"**Error Log Channel**: {error_channel.mention if error_channel else '❌ Disabled'}"]
    embed.add_field(name="General Settings", value="\n".join(general_settings), inline=False)

    # Cog management settings
    load_all_cogs = bot.config.get("load_all_cogs", False)
    enabled_cogs_count = len(bot.config.get("enabled_cogs", []))
    disabled_cogs_count = len(bot.config.get("disabled_cogs", []))

    cog_settings = [
        f"**Load All Cogs**: {'✅ Enabled' if load_all_cogs else '❌ Disabled'}",
        f"**Enabled Cogs**: {enabled_cogs_count}",
        f"**Disabled Cogs**: {disabled_cogs_count}",
        f"**Active Cogs**: {len(bot.cogs)}",
    ]
    embed.add_field(name="Cog Management", value="\n".join(cog_settings), inline=False)

    # Discord intents
    intents = [
        f"**Message Content**: {'✅ Enabled' if bot.intents.message_content else '❌ Disabled'}",
        f"**Members**: {'✅ Enabled' if bot.intents.members else '❌ Disabled'}",
        f"**Presences**: {'✅ Enabled' if bot.intents.presences else '❌ Disabled'}",
    ]
    embed.add_field(name="Discord Intents", value="\n".join(intents), inline=False)

    # Bot status
    uptime = discord.utils.utcnow() - bot.user.created_at
    days, remainder = divmod(int(uptime.total_seconds()), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

    status_emoji = "✅" if bot.is_ready() else "⏳"

    status_info = [
        f"**Status**: {status_emoji} {'Connected' if bot.is_ready() else 'Connecting'}",
        f"**Uptime**: {uptime_str}",
        f"**Latency**: {round(bot.latency * 1000)}ms",
        f"**Servers**: {len(bot.guilds)}",
    ]
    embed.add_field(name="Bot Status", value="\n".join(status_info), inline=False)

    # Footer with version info
    embed.set_footer(text=f"User ID: {bot.user.id} | Use {prefix}help to see available commands")

    await ctx.send(embed=embed)


@bot.group(name="config", invoke_without_command=True)
async def config_group(ctx):
    """Commands for managing bot configuration"""
    if ctx.invoked_subcommand is None:
        await ctx.invoke(bot.get_command("settings"))


@config_group.command(name="prefix")
async def config_prefix(ctx, new_prefix: str = None):
    """View or change the bot command prefix.

    Parameters:
    -----------
    new_prefix: The new prefix to use. If omitted, shows current prefix.

    Examples:
    ---------
    $config prefix !
    $config prefix
    """
    if new_prefix is None:
        current_prefix = bot.config.get("prefix", "$")
        await ctx.send(f"Current command prefix: `{current_prefix}`")
    else:
        # Ensure prefix isn't too long
        if len(new_prefix) > 5:
            return await ctx.send("❌ Prefix must be 5 characters or less")

        bot.config.config["prefix"] = new_prefix
        bot.config.save_config()
        bot.command_prefix = new_prefix
        await ctx.send(f"✅ Command prefix changed to: `{new_prefix}`")


@config_group.command(name="error_channel")
async def config_error_channel(ctx, channel: discord.TextChannel = None):
    """Set or view the channel for logging command errors.

    Parameters:
    -----------
    channel: The channel to use. If omitted, shows current channel.

    Examples:
    ---------
    $config error_channel #bot-errors
    $config error_channel
    """
    if channel is None:
        error_channel_id = bot.config.get("error_log_channel", None)
        if error_channel_id:
            channel = bot.get_channel(int(error_channel_id))
            if channel:
                await ctx.send(f"Command errors are being logged to {channel.mention}")
            else:
                await ctx.send(f"Error logging is set to channel ID `{error_channel_id}` but I can't find that channel")
        else:
            await ctx.send("Command error logging is disabled")
    else:
        await ctx.invoke(bot.get_command("set_error_log_channel"), channel=channel)


@config_group.command(name="toggle")
async def config_toggle(ctx, setting_name: str, value: bool = None):
    """Toggle a configuration setting.

    Args:
        setting_name: Name of the setting to toggle
        value: Optional boolean value to set explicitly. If omitted, toggles current value.

    Examples:
        $config toggle debug_mode        (toggle debug mode on/off)
        $config toggle debug_mode True   (explicitly enable debug mode)
    """
    setting_name = setting_name.lower()
    valid_settings = ["debug_mode", "verbose_logging"]  # Add more as needed

    if setting_name not in valid_settings:
        return await ctx.send(f"❌ Unknown setting: `{setting_name}`\nValid settings: {', '.join([f'`{s}`' for s in valid_settings])}")

    # Get current value, default to False if not found
    current_value = bot.config.get(setting_name, False)

    # Determine new value (toggle if not specified)
    new_value = not current_value if value is None else value

    # Update the setting
    bot.config.config[setting_name] = new_value
    bot.config.save_config()

    # Report the new state
    status = "✅ Enabled" if new_value else "❌ Disabled"
    await ctx.send(f"Setting `{setting_name}` is now {status}")


@bot.group(name="command_type", aliases=["cmdtype"], invoke_without_command=True)
async def command_type_group(ctx):
    """Manage command types (prefix, slash, both, none)"""
    if ctx.invoked_subcommand is None:
        # Show current settings
        embed = discord.Embed(title="Command Type Settings", description="Control how commands are invoked", color=discord.Color.blue())

        default_mode = bot.config.get("command_type_mode", "prefix")
        embed.add_field(name="Default Mode", value=f"`{default_mode}`", inline=False)

        # Show custom command types
        command_types = bot.config.get("command_types", {})
        if command_types:
            custom_settings = "\n".join([f"`{cmd}`: {mode}" for cmd, mode in sorted(command_types.items())])
            embed.add_field(name="Custom Command Settings", value=custom_settings, inline=False)
        else:
            embed.add_field(name="Custom Command Settings", value="No custom settings configured", inline=False)

        # Add explanation
        embed.add_field(
            name="Command Type Options",
            value="`prefix`: Traditional commands only (e.g., $command)\n"
            "`slash`: Slash commands only (e.g., /command)\n"
            "`both`: Both prefix and slash commands\n"
            "`none`: Command disabled",
            inline=False,
        )

        await ctx.send(embed=embed)


@command_type_group.command(name="set_default")
async def command_type_set_default(ctx, mode: str):
    """Set the default command type mode.

    Args:
        mode: The mode to set (prefix, slash, both, none)

    Examples:
        $command_type set_default both
        $command_type set_default slash
    """
    valid_modes = ["prefix", "slash", "both", "none"]
    if mode.lower() not in valid_modes:
        return await ctx.send(f"❌ Invalid mode. Valid options: {', '.join(valid_modes)}")

    # Update the setting
    bot.config.config["command_type_mode"] = mode.lower()
    bot.config.save_config()

    await ctx.send(f"✅ Default command type mode set to: `{mode.lower()}`")

    # Remind about syncing
    await ctx.send("ℹ️ Remember to use `$command_type sync` to apply changes to slash commands")


@command_type_group.command(name="set")
async def command_type_set(ctx, command_name: str, mode: str):
    """Set the command type for a specific command.

    Args:
        command_name: The command to configure
        mode: The mode to set (prefix, slash, both, none)

    Examples:
        $command_type set settings slash
        $command_type set help prefix
    """
    valid_modes = ["prefix", "slash", "both", "none"]
    if mode.lower() not in valid_modes:
        return await ctx.send(f"❌ Invalid mode. Valid options: {', '.join(valid_modes)}")

    # Check if command exists
    cmd = bot.get_command(command_name)
    if not cmd:
        return await ctx.send(f"❌ Command '{command_name}' not found")

    # Use the root command name if it's a subcommand
    root_name = cmd.qualified_name

    # Update the setting
    command_types = bot.config.get("command_types", {})
    command_types[root_name] = mode.lower()
    bot.config.config["command_types"] = command_types
    bot.config.save_config()

    await ctx.send(f"✅ Command `{root_name}` set to mode: `{mode.lower()}`")

    # Remind about syncing
    await ctx.send("ℹ️ Remember to use `$command_type sync` to apply changes to slash commands")


@command_type_group.command(name="reset")
async def command_type_reset(ctx, command_name: str):
    """Reset a command to use the default command type.

    Args:
        command_name: The command to reset

    Examples:
        $command_type reset settings
    """
    # Check if command exists
    cmd = bot.get_command(command_name)
    if not cmd:
        return await ctx.send(f"❌ Command '{command_name}' not found")

    # Use the root command name if it's a subcommand
    root_name = cmd.qualified_name

    # Update the setting
    command_types = bot.config.get("command_types", {})
    if root_name in command_types:
        del command_types[root_name]
        bot.config.config["command_types"] = command_types
        bot.config.save_config()

        default_mode = bot.config.get("command_type_mode", "both")
        await ctx.send(f"✅ Command `{root_name}` reset to default mode: `{default_mode}`")
    else:
        default_mode = bot.config.get("command_type_mode", "both")
        await ctx.send(f"ℹ️ Command `{root_name}` is already using default mode: `{default_mode}`")

    # Remind about syncing
    await ctx.send("ℹ️ Remember to use `$command_type sync` to apply changes to slash commands")


@command_type_group.command(name="sync")
async def command_type_sync(ctx):
    """Sync command settings with Discord."""
    await ctx.send("🔄 Syncing commands with Discord...")

    try:
        # Get registered commands
        commands = []
        for command in bot.walk_commands():
            # Skip commands that shouldn't be slash commands
            command_type = bot.command_type_manager.get_command_type(command.qualified_name)
            if command_type in ["slash", "both"]:
                # Convert command to slash command format
                slash_command = {
                    "name": command.name,
                    "description": command.help or "No description available",
                    "options": [],  # Add parameter handling if needed
                }
                commands.append(slash_command)

        # Sync with Discord
        if ctx.guild:
            # Sync to specific guild
            synced = await bot.tree.sync(guild=ctx.guild)
        else:
            # Global sync
            synced = await bot.tree.sync()

        await ctx.send(f"✅ Synced {len(synced)} command(s) with Discord")

    except Exception as e:
        await ctx.send(f"❌ Error syncing commands: {str(e)}")
        bot.logger.error(f"Command sync error: {e}", exc_info=True)


@bot.event
async def on_close():
    """Clean up resources when the bot is shutting down."""
    # Stop the file system observer
    bot.cog_manager.stop_observer()


def main():
    """Main entry point for the Discord bot."""
    bot.run(getenv("DISCORD_TOKEN"), log_level=logging.INFO)


# Bot instance is available for import
__all__ = ["bot", "DiscordBot", "main"]

# Run bot if this module is executed directly
if __name__ == "__main__":
    main()

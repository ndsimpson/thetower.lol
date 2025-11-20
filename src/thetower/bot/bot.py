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
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

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
            command_prefix=self._get_prefix,
            intents=intents,
            case_insensitive=True,
            # Add application_id for slash commands support
            application_id=int(getenv("DISCORD_APPLICATION_ID", 0)),
            interaction_timeout=900,  # 15 minutes timeout for slash commands
        )
        self.logger = logger
        self.cog_manager = CogManager(self)

        # Set up logging with UTC timestamps
        formatter = logging.Formatter("%(asctime)s UTC [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        formatter.converter = lambda *args: datetime.datetime.now(timezone.utc).timetuple()

        # Configure the root logger
        root_logger = logging.getLogger("thetower.bot")
        if not root_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)

    def _get_prefix(self, bot, message):
        """Get the command prefix(es) for a guild.

        Returns the guild-specific prefix(es) if set, otherwise the default prefix.
        Supports DMs by falling back to default prefix.
        Can return a single prefix or a list of prefixes.
        """
        # Get default prefixes from config (no hardcoded fallback)
        default_prefixes = self.config.get("prefixes", [])

        # In DMs, use default prefixes
        if message.guild is None:
            return default_prefixes

        # Get guild-specific prefix(es)
        guild_prefixes = self.config.get_guild_prefix(message.guild.id)

        # If guild has custom prefix(es), use them; otherwise use default
        if guild_prefixes:
            # If it's a list, return the list; if it's a string, return as-is
            return guild_prefixes
        return default_prefixes

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


@cog_group.command(name="toggle")
async def cog_toggle(ctx, setting_name: str, value: bool = None):
    """Toggle a cog-related setting.

    Args:
        setting_name: Name of the setting to toggle (load_all)
        value: Optional boolean value to set explicitly. If omitted, toggles current value.

    Examples:
        $cog toggle load_all        (toggle the load_all_cogs setting)
        $cog toggle load_all True   (explicitly enable load_all_cogs)
    """
    setting_name = setting_name.lower()

    # Handle load_all_cogs setting (deprecated - kept for backwards compatibility)
    if setting_name in ["load_all", "load_all_cogs"]:
        await ctx.send("⚠️ The `load_all_cogs` setting is deprecated. Bot owner now controls which cogs are loaded globally.")
        return

    # Unknown setting
    await ctx.send(f"❌ Unknown setting: `{setting_name}`")


# Permission Management Commands
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
    default_prefixes = bot.config.get("prefixes", [])
    guild_prefixes = bot.config.get_guild_prefix(ctx.guild.id) if ctx.guild else None

    # Format prefix display
    if guild_prefixes:
        if isinstance(guild_prefixes, list):
            prefix_list = ", ".join(f"`{p}`" for p in guild_prefixes)
            current_prefix = guild_prefixes[0] if guild_prefixes else "!"
            prefix_display = f"**Prefix(es)**: {prefix_list} (server-specific)"
        else:
            current_prefix = guild_prefixes
            prefix_display = f"**Prefix**: `{guild_prefixes}` (server-specific)"
    else:
        if isinstance(default_prefixes, list):
            if default_prefixes:
                prefix_list = ", ".join(f"`{p}`" for p in default_prefixes)
                current_prefix = default_prefixes[0]
                prefix_display = f"**Prefix(es)**: {prefix_list} (default)"
            else:
                current_prefix = "!"
                prefix_display = "**Prefix(es)**: None configured (default)"
        else:
            current_prefix = default_prefixes or "!"
            prefix_display = f"**Prefix**: `{default_prefixes or 'None'}` (default)"

    error_channel_id = bot.config.get("error_log_channel", None)
    error_channel = bot.get_channel(int(error_channel_id)) if error_channel_id else None

    # General settings section
    general_settings = [prefix_display, f"**Error Log Channel**: {error_channel.mention if error_channel else '❌ Disabled'}"]
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
    embed.set_footer(text=f"User ID: {bot.user.id} | Use {current_prefix}help to see available commands")

    await ctx.send(embed=embed)


@bot.group(name="config", invoke_without_command=True)
async def config_group(ctx):
    """Commands for managing bot configuration"""
    if ctx.invoked_subcommand is None:
        await ctx.invoke(bot.get_command("settings"))


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


@bot.command()
async def sync_commands(ctx):
    """Manually sync slash commands for this guild.

    This command is useful if slash commands are not appearing in Discord.
    Only server owners or the bot owner can use this command.
    """
    if not ctx.guild:
        await ctx.send("❌ This command can only be used in a server.")
        return

    # Check if user has permission (guild owner or bot owner)
    is_bot_owner = await bot.is_owner(ctx.author)
    is_guild_owner = ctx.author.id == ctx.guild.owner_id

    if not (is_bot_owner or is_guild_owner):
        await ctx.send("❌ Only the server owner or bot owner can sync commands.")
        return

    try:
        await ctx.send("🔄 Syncing slash commands for this guild...")

        # Log commands being synced
        commands = [cmd.name for cmd in bot.tree.get_commands()]
        logger.info(f"Syncing {len(commands)} slash commands for guild {ctx.guild.id} ({ctx.guild.name}): {', '.join(commands)}")

        await bot.tree.sync(guild=ctx.guild)
        await ctx.send("✅ Slash commands synced successfully!")
        logger.info(f"Successfully synced slash commands for guild {ctx.guild.id} ({ctx.guild.name})")
    except Exception as e:
        await ctx.send(f"❌ Failed to sync commands: {e}")
        logger.error(f"Failed to manually sync commands for guild {ctx.guild.id}: {e}")


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
    is_bot_owner = await bot.is_owner(interaction.user)
    guild_id = interaction.guild.id if interaction.guild else None

    # Check if user has permission
    if not is_bot_owner:
        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Settings can only be accessed in a server (unless you're the bot owner).", ephemeral=True
            )
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Only the server owner or bot owner can access settings.", ephemeral=True)

    # Create main settings view
    view = SettingsMainView(is_bot_owner, guild_id)

    embed = discord.Embed(title="⚙️ Settings", description="Select a category to manage", color=discord.Color.blue())

    if is_bot_owner:
        embed.add_field(name="👑 Bot Owner", value="You have full access to all settings", inline=False)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


def main():
    """Main entry point for the Discord bot."""
    bot.run(getenv("DISCORD_TOKEN"), log_level=logging.INFO)


# Bot instance is available for import
__all__ = ["bot", "DiscordBot", "main"]

# Run bot if this module is executed directly
if __name__ == "__main__":
    main()

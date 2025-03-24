"""
Unified permission management system for the bot.

This module provides centralized command permission checking and management
for both global commands and cog-specific commands.
"""

# Standard library imports
import logging
from typing import Dict, Any, List, Optional, Union

# Third-party imports
import discord
from discord.ext import commands
from discord.ext.commands import Context

# Local imports
from fish_bot.exceptions import UserUnauthorized, ChannelUnauthorized

logger = logging.getLogger(__name__)


class PermissionManager:
    """
    Central manager for Discord bot command permissions.

    Provides methods to check and manage permissions for both global and
    cog-specific commands uniformly.
    """

    def __init__(self, config_manager):
        """
        Initialize the permission manager with a config manager.

        Args:
            config_manager: The configuration manager to use for storing/retrieving permissions
        """
        self.config = config_manager
        self.permissions = self._load_permissions()

    def _load_permissions(self) -> Dict[str, Any]:
        """
        Load command permissions from configuration.

        Returns:
            Dict containing the command permissions structure
        """
        try:
            permissions = self.config.get("command_permissions", {"commands": {}})
            return permissions
        except Exception as e:
            logger.error(f"Failed to load command permissions: {e}")
            return {"commands": {}}

    def reload_permissions(self) -> None:
        """Reload permissions from the configuration."""
        self.permissions = self._load_permissions()

    def _get_primary_command_name(self, ctx_or_bot, command_name: str = None) -> str:
        """
        Get the primary name of a command, resolving from alias if needed.

        Args:
            ctx_or_bot: Either a Context object or Bot object
            command_name: Optional command name override

        Returns:
            The primary command name
        """
        # Get the bot instance
        bot = ctx_or_bot.bot if hasattr(ctx_or_bot, 'bot') else ctx_or_bot

        # If no command_name provided and we have a context, use context's command
        if command_name is None and hasattr(ctx_or_bot, 'command'):
            return ctx_or_bot.command.name

        # Try to get the command
        cmd = bot.get_command(command_name)

        # If command can't be found, return the original name
        if not cmd:
            return command_name

        # Return the primary command name
        return cmd.name

    async def check_command_permissions(self, ctx: Context, command_name: str = None) -> bool:
        """
        Check if a command can be executed in the current context.

        Args:
            ctx: The command context
            command_name: Optional command name override (defaults to ctx.command.name)

        Returns:
            True if the command is allowed, False otherwise

        Raises:
            ChannelUnauthorized: If the channel is not authorized for this command
            UserUnauthorized: If the user is not authorized for this command
        """
        if not command_name:
            command_name = ctx.command.name

        # Resolve to primary command name
        primary_name = self._get_primary_command_name(ctx, command_name)

        # Always allow the help command
        if primary_name == 'help':
            return True

        # Always allow DMs from bot owner
        if ctx.guild is None and await ctx.bot.is_owner(ctx.author):
            return True

        # Check for wildcard command permission
        wildcard_config = self.permissions["commands"].get("*", {})
        if str(ctx.channel.id) in wildcard_config.get("channels", {}):
            channel_config = wildcard_config["channels"].get(str(ctx.channel.id), {})

            # If not public, check user permissions
            if not channel_config.get("public", False):
                if str(ctx.author.id) not in channel_config.get("authorized_users", []):
                    logger.warning(
                        f"Command '{primary_name}' blocked - unauthorized user in wildcard channel. "
                        f"User: {ctx.author} (ID: {ctx.author.id})"
                    )
                    raise UserUnauthorized(ctx.author)
            return True

        # Get command-specific permissions
        command_config = self.permissions["commands"].get(primary_name, {})
        channel_config = command_config.get("channels", {}).get(str(ctx.channel.id))

        # Check for wildcard channel permission
        if "*" in command_config.get("channels", {}):
            wildcard_channel_config = command_config["channels"].get("*", {})
            # If wildcard is public or user is authorized
            if wildcard_channel_config.get("public", False) or \
               str(ctx.author.id) in wildcard_channel_config.get("authorized_users", []):
                return True

        # Check channel permissions
        if not channel_config:
            logger.warning(
                f"Command '{primary_name}' blocked - unauthorized channel. "
                f"Channel: {ctx.channel} (ID: {ctx.channel.id})"
            )
            raise ChannelUnauthorized(ctx.channel)

        # Check user permissions if channel is not public
        if not channel_config.get("public", False):
            if str(ctx.author.id) not in channel_config.get("authorized_users", []):
                logger.warning(
                    f"Command '{primary_name}' blocked - unauthorized user. "
                    f"User: {ctx.author} (ID: {ctx.author.id})"
                )
                raise UserUnauthorized(ctx.author)

        return True

    def _resolve_command_name(self, bot, command_name: str) -> str:
        """
        Resolve a command name to its primary name, handling aliases.

        Args:
            bot: The bot instance
            command_name: The command name or alias

        Returns:
            The primary name of the command
        """
        cmd = bot.get_command(command_name)
        return cmd.name if cmd else command_name

    def add_command_channel(self, bot, command: str, channel_id: str, public: bool = True) -> bool:
        """Add a channel to command permissions.

        Args:
            bot: The bot instance
            command: Command name
            channel_id: Channel ID to add
            public: Whether command is public in channel

        Returns:
            bool: True if successful
        """
        primary_name = self._get_primary_command_name(bot, command)
        if not primary_name:
            return False

        return self.config.add_command_channel(primary_name, channel_id, public)

    async def cmd_add_channel(self, ctx, command: str, channel_input: str, public: bool = False) -> tuple[bool, str]:
        """Add a channel to command permissions.

        Args:
            ctx: The command context
            command: The command name or alias
            channel_input: The channel input
            public: Whether the command should be public in this channel

        Returns:
            tuple[bool, str]: (success, message)
        """
        # Handle wildcard channel case
        if channel_input == '*':
            channel_id = '*'
        else:
            # Try to resolve channel from input
            try:
                channel = await commands.TextChannelConverter().convert(ctx, channel_input)
                channel_id = str(channel.id)
            except commands.ChannelNotFound:
                return False, f"Could not find channel/thread: {channel_input}"

        # Resolve to primary command name
        cmd_obj = ctx.bot.get_command(command)
        if cmd_obj:
            primary_name = cmd_obj.name
            display_name = f"'{primary_name}'"
            if cmd_obj.aliases:
                display_name += f" (alias of {command})" if command != primary_name else ""
        else:
            primary_name = command
            display_name = f"'{primary_name}'"

        if self.add_command_channel(ctx.bot, primary_name, channel_id, public):
            status = "public" if public else "non-public"
            return True, f"✅ Added channel {channel.mention} to command {display_name} permissions ({status})"
        else:
            await ctx.send(f"❌ Failed to add channel {channel.mention} to command {display_name} permissions")
            return False, "Failed to add channel permissions"

    def remove_command_channel(self, bot, command: str, channel_id: str) -> bool:
        """
        Remove a channel from command permissions.

        Args:
            bot: The bot instance
            command: The command name or alias
            channel_id: The channel ID

        Returns:
            True if successful, False otherwise
        """
        primary_name = self._resolve_command_name(bot, command)
        return self.config.remove_command_channel(primary_name, channel_id)

    def add_authorized_user(self, bot, command: str, channel_id: str, user_id: str) -> bool:
        """
        Add an authorized user to a command channel.

        Args:
            bot: The bot instance
            command: The command name or alias
            channel_id: The channel ID
            user_id: The user ID

        Returns:
            True if successful, False otherwise
        """
        primary_name = self._resolve_command_name(bot, command)
        return self.config.add_authorized_user(primary_name, channel_id, user_id)

    def remove_authorized_user(self, bot, command: str, channel_id: str, user_id: str) -> bool:
        """
        Remove an authorized user from a command channel.

        Args:
            bot: The bot instance
            command: The command name or alias
            channel_id: The channel ID
            user_id: The user ID

        Returns:
            True if successful, False otherwise
        """
        primary_name = self._resolve_command_name(bot, command)
        return self.config.remove_authorized_user(primary_name, channel_id, user_id)

    def set_channel_public(self, bot, command: str, channel_id: str, public: bool = True) -> bool:
        """
        Set whether a command is public in a channel.

        Args:
            bot: The bot instance
            command: The command name or alias
            channel_id: The channel ID
            public: Whether the command is public

        Returns:
            True if successful, False otherwise
        """
        try:
            primary_name = self._resolve_command_name(bot, command)
            permissions = self.config.get("command_permissions", {"commands": {}})

            # Initialize commands dict if it doesn't exist
            commands = permissions.setdefault("commands", {})

            # Initialize command config if it doesn't exist
            command_config = commands.setdefault(primary_name, {})

            # Initialize channels dict if it doesn't exist
            channels = command_config.setdefault("channels", {})

            # Initialize channel config if it doesn't exist
            channel_config = channels.setdefault(channel_id, {})

            # Set public flag
            channel_config["public"] = public

            # Save updated permissions
            self.config.config["command_permissions"] = permissions
            self.config.save_config()

            # Reload permissions
            self.permissions = permissions

            return True
        except Exception as e:
            logger.error(f"Failed to set channel public flag: {e}")
            return False

    def get_command_permissions(self, command: str, bot=None) -> Dict[str, Any]:
        """
        Get permissions for a specific command.

        Args:
            command: The command name or alias
            bot: Optional bot instance to resolve aliases

        Returns:
            Dict containing the command permissions
        """
        if bot:
            primary_name = self._resolve_command_name(bot, command)
        else:
            primary_name = command

        return self.permissions.get("commands", {}).get(primary_name, {})

    def get_authorized_channels(self, command: str, bot=None) -> List[str]:
        """
        Get all channels authorized for a command.

        Args:
            command: The command name or alias
            bot: Optional bot instance to resolve aliases

        Returns:
            List of channel IDs authorized for the command
        """
        if bot:
            primary_name = self._resolve_command_name(bot, command)
        else:
            primary_name = command

        command_config = self.get_command_permissions(primary_name)
        channels = command_config.get("channels", {})

        # Also check the wildcard command
        wildcard_channels = self.permissions.get("commands", {}).get("*", {}).get("channels", {})

        # Combine both sets of channels
        return list(set(channels.keys()).union(wildcard_channels.keys()))

    def get_authorized_users(self, command: str, channel_id: str, bot=None) -> List[str]:
        """
        Get all users authorized for a command in a channel.

        Args:
            command: The command name or alias
            channel_id: The channel ID
            bot: Optional bot instance to resolve aliases

        Returns:
            List of user IDs authorized for the command in the channel
        """
        if bot:
            primary_name = self._resolve_command_name(bot, command)
        else:
            primary_name = command

        command_config = self.get_command_permissions(primary_name)
        channel_config = command_config.get("channels", {}).get(channel_id, {})

        return channel_config.get("authorized_users", [])

    def is_command_public(self, command: str, channel_id: str, bot=None) -> bool:
        """
        Check if a command is public in a channel.

        Args:
            command: The command name or alias
            channel_id: The channel ID
            bot: Optional bot instance to resolve aliases

        Returns:
            True if the command is public, False otherwise
        """
        if bot:
            primary_name = self._resolve_command_name(bot, command)
        else:
            primary_name = command

        # Check specific command channel
        command_config = self.get_command_permissions(primary_name)
        channel_config = command_config.get("channels", {}).get(channel_id, {})

        if channel_config.get("public", False):
            return True

        # Check wildcard command
        wildcard_config = self.permissions.get("commands", {}).get("*", {})
        wildcard_channel_config = wildcard_config.get("channels", {}).get(channel_id, {})

        return wildcard_channel_config.get("public", False)

    @staticmethod
    async def resolve_channel_from_input(
        ctx: commands.Context,
        channel_input: str
    ) -> Optional[Union[discord.TextChannel, discord.Thread]]:
        """
        Resolve a channel from different input types (mention, ID, name, or search).

        Args:
            ctx: The command context
            channel_input: The channel input (mention, ID, name, or search term)

        Returns:
            discord.abc.GuildChannel or None: The resolved channel/thread, or None if not found

        Examples:
            - #bot-commands (mention)
            - 123456789 (ID)
            - bot-commands (name)
            - Bot Commands (display name)
            - commands (partial name search)
        """
        channel = None

        # Check if it's a channel mention
        if ctx.message.channel_mentions:
            for mentioned_channel in ctx.message.channel_mentions:
                if f'<#{mentioned_channel.id}>' in channel_input:
                    return mentioned_channel

        # Try to extract ID from mention format (<#123456789>)
        if channel_input.startswith('<#') and channel_input.endswith('>'):
            try:
                channel_id = int(channel_input.strip('<#>'))
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    return channel

                # Check threads if not found as regular channel
                for thread in ctx.guild.threads:
                    if thread.id == channel_id:
                        return thread

                # Try to fetch thread directly
                try:
                    thread = await ctx.guild.fetch_channel(channel_id)
                    if isinstance(thread, (discord.Thread, discord.ForumChannel)):
                        return thread
                except discord.NotFound:
                    pass
            except (ValueError, TypeError):
                pass

        # Try direct ID
        try:
            channel_id = int(channel_input)
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                return channel

            # Check threads
            for thread in ctx.guild.threads:
                if thread.id == channel_id:
                    return thread

            # Try to fetch thread directly
            try:
                thread = await ctx.guild.fetch_channel(channel_id)
                if isinstance(thread, (discord.Thread, discord.ForumChannel)):
                    return thread
            except discord.NotFound:
                pass
        except (ValueError, TypeError):
            # Not a valid ID, continue with name search
            pass

        # Try exact name match first (case-insensitive)
        channel = discord.utils.get(
            ctx.guild.text_channels,
            name=channel_input.lower().replace(' ', '-')
        )
        if channel:
            return channel

        # Try exact display name match
        channel = discord.utils.get(
            ctx.guild.text_channels,
            name=channel_input.lower().replace(' ', '-')
        )
        if channel:
            return channel

        # Try thread exact name match
        channel = discord.utils.get(
            ctx.guild.threads,
            name=channel_input
        )
        if channel:
            return channel

        # If no exact match, try partial name search
        channels = [c for c in ctx.guild.text_channels
                    if channel_input.lower() in c.name.lower() or
                    channel_input.lower() in c.name.lower().replace('-', ' ')]

        if len(channels) == 1:
            return channels[0]
        elif len(channels) > 1:
            # If multiple matches, send disambiguation message
            channel_list = "\n".join([f"- {c.mention} ({c.name})" for c in channels[:5]])
            if len(channels) > 5:
                channel_list += f"\n...and {len(channels) - 5} more"
            await ctx.send(f"Multiple channels found matching '{channel_input}':\n{channel_list}\n"
                           "Please be more specific or use the channel ID/mention.")
            return None

        # Check threads for partial matches as last resort
        threads = [t for t in ctx.guild.threads
                   if channel_input.lower() in t.name.lower()]

        if len(threads) == 1:
            return threads[0]
        elif len(threads) > 1:
            thread_list = "\n".join([f"- {t.mention} ({t.name})" for t in threads[:5]])
            if len(threads) > 5:
                thread_list += f"\n...and {len(threads) - 5} more"
            await ctx.send(f"Multiple threads found matching '{channel_input}':\n{thread_list}\n"
                           "Please be more specific or use the thread ID/mention.")
            return None

        return None

    async def cmd_remove_channel(self, ctx, command: str, channel_input: str) -> bool:
        """Remove a channel from command permissions.

        Args:
            ctx: The command context
            command: The command name or alias
            channel_input: The channel input

        Returns:
            bool: True if successful, False otherwise
        """
        channel = await self.resolve_channel_from_input(ctx, channel_input)

        if not channel:
            await ctx.send(f"Could not find channel '{channel_input}'. Please provide a valid channel mention, name, or ID.")
            return False

        channel_id = str(channel.id)

        # Resolve to primary command name
        cmd_obj = ctx.bot.get_command(command)
        if cmd_obj:
            primary_name = cmd_obj.name
            display_name = f"'{primary_name}'"
            if cmd_obj.aliases:
                display_name += f" (alias of {command})" if command != primary_name else ""
        else:
            primary_name = command
            display_name = f"'{primary_name}'"

        if self.remove_command_channel(ctx.bot, primary_name, channel_id):
            await ctx.send(f"✅ Removed channel {channel.mention} from command {display_name} permissions")
            return True
        else:
            await ctx.send(f"❌ Failed to remove channel {channel.mention} from command {display_name} permissions")
            return False

    async def cmd_add_user(self, ctx, command: str, channel_input: str, user: discord.Member) -> bool:
        """Add a user to authorized users for a command channel.

        Args:
            ctx: The command context
            command: The command name or alias
            channel_input: The channel input (mention, ID, or name)
            user: The user to add

        Returns:
            bool: True if successful, False otherwise
        """
        # Resolve channel from input
        channel = await self.resolve_channel_from_input(ctx, channel_input)

        if not channel:
            await ctx.send(f"Could not find channel '{channel_input}'. Please provide a valid channel mention, name, or ID.")
            return False

        channel_id = str(channel.id)
        user_id = str(user.id)

        # Resolve to primary command name
        cmd_obj = ctx.bot.get_command(command)
        if cmd_obj:
            primary_name = cmd_obj.name
            display_name = f"'{primary_name}'"
            if cmd_obj.aliases:
                display_name += f" (alias of {command})" if command != primary_name else ""
        else:
            primary_name = command
            display_name = f"'{primary_name}'"

        if self.add_authorized_user(ctx.bot, primary_name, channel_id, user_id):
            await ctx.send(f"✅ Added {user.mention} to authorized users for command {display_name} in channel {channel.mention}")
            return True
        else:
            await ctx.send(f"❌ Failed to add {user.mention} to authorized users for command {display_name} in channel {channel.mention}")
            return False

    async def cmd_remove_user(self, ctx, command: str, channel_input: str, user: discord.Member) -> bool:
        """Remove a user from authorized users for a command channel.

        Args:
            ctx: The command context
            command: The command name or alias
            channel_input: The channel input (mention, ID, or name)
            user: The user to remove

        Returns:
            bool: True if successful, False otherwise
        """
        # Resolve channel from input
        channel = await self.resolve_channel_from_input(ctx, channel_input)

        if not channel:
            await ctx.send(f"Could not find channel '{channel_input}'. Please provide a valid channel mention, name, or ID.")
            return False

        channel_id = str(channel.id)
        user_id = str(user.id)

        # Resolve to primary command name
        cmd_obj = ctx.bot.get_command(command)
        if cmd_obj:
            primary_name = cmd_obj.name
            display_name = f"'{primary_name}'"
            if cmd_obj.aliases:
                display_name += f" (alias of {command})" if command != primary_name else ""
        else:
            primary_name = command
            display_name = f"'{primary_name}'"

        if self.remove_authorized_user(ctx.bot, primary_name, channel_id, user_id):
            await ctx.send(f"✅ Removed {user.mention} from authorized users for command {display_name} in channel {channel.mention}")
            return True
        else:
            await ctx.send(f"❌ Failed to remove {user.mention} from authorized users for command {display_name} in channel {channel.mention}")
            return False

    async def show_permissions_overview(self, ctx: Context) -> None:
        """
        Display an overview of command permissions.

        Args:
            ctx: The command context
        """
        embed = discord.Embed(
            title="Permission Management",
            description="Overview of command permissions",
            color=discord.Color.blue()
        )

        # List all commands with permissions
        commands_with_perms = list(self.permissions.get("commands", {}).keys())
        if commands_with_perms:
            commands_list = "\n".join([f"• {cmd}" for cmd in commands_with_perms])
            embed.add_field(
                name="Commands with Permissions",
                value=commands_list,
                inline=False
            )
        else:
            embed.add_field(
                name="Commands with Permissions",
                value="No commands have permissions set",
                inline=False
            )

        # Add help text
        embed.add_field(
            name="Available Commands",
            value=(
                "• `!perm list [command]` - List permissions for a command\n"
                "• `!perm add_channel <command> <channel> [public]` - Add channel\n"
                "• `!perm remove_channel <command> <channel>` - Remove channel\n"
                "• `!perm add_user <command> <channel> <user>` - Add user\n"
                "• `!perm remove_user <command> <channel> <user>` - Remove user\n"
                "• `!perm set_public <command> <channel> [true/false]` - Set public status"
            ),
            inline=False
        )

        await ctx.send(embed=embed)

    def _get_command_aliases(self, bot, command_name: str) -> List[str]:
        """
        Get all aliases for a command.

        Args:
            bot: The bot instance
            command_name: The command name

        Returns:
            List of command aliases
        """
        cmd = bot.get_command(command_name)
        return cmd.aliases if cmd and hasattr(cmd, 'aliases') else []

    async def show_permissions(self, ctx: Context, command_name: Optional[str] = None) -> None:
        """
        Display permissions for a specific command or all commands.

        Args:
            ctx: The command context
            command_name: Optional command name to show permissions for
        """
        bot = ctx.bot
        commands_dict = self.permissions.get("commands", {})

        if command_name:
            # Resolve to primary command name if it's an alias
            cmd = bot.get_command(command_name)
            if cmd:
                primary_name = cmd.name
                aliases = cmd.aliases if hasattr(cmd, 'aliases') else []
            else:
                primary_name = command_name
                aliases = []

            # Show permissions for a specific command
            if primary_name not in commands_dict and primary_name != "*":
                return await ctx.send(f"No permissions set for command `{primary_name}`")

            embed = discord.Embed(
                title=f"Permissions for `{primary_name}`",
                color=discord.Color.blue()
            )

            # Add aliases information if any exist
            if aliases:
                embed.description = f"**Aliases**: {', '.join([f'`{alias}`' for alias in aliases])}"

            command_config = commands_dict.get(primary_name, {})
            channels = command_config.get("channels", {})

            if not channels:
                if not embed.description:
                    embed.description = "No channels configured for this command"
                else:
                    embed.description += "\n\nNo channels configured for this command"
            else:
                for channel_id, channel_config in channels.items():
                    if channel_id == "*":
                        channel_desc = "All channels (wildcard)"
                    else:
                        channel = bot.get_channel(int(channel_id))
                        channel_desc = f"#{channel.name}" if channel else f"Unknown ({channel_id})"

                    is_public = channel_config.get("public", False)
                    status = "Public" if is_public else "Non-public"

                    value = f"**Status**: {status}\n"

                    if not is_public:
                        users = channel_config.get("authorized_users", [])
                        if users:
                            user_mentions = []
                            for user_id in users[:10]:  # Limit to first 10 users
                                user = bot.get_user(int(user_id))
                                user_mentions.append(f"<@{user_id}>" if user else f"ID:{user_id}")

                            if len(users) > 10:
                                user_mentions.append(f"...and {len(users) - 10} more")

                            value += f"**Authorized Users**: {', '.join(user_mentions)}"
                        else:
                            value += "**Authorized Users**: None"

                    embed.add_field(
                        name=f"Channel: {channel_desc}",
                        value=value,
                        inline=False
                    )

            await ctx.send(embed=embed)
        else:
            # Show overview of all commands
            embed = discord.Embed(
                title="Command Permissions Overview",
                description="List of commands with their permissions",
                color=discord.Color.blue()
            )

            if not commands_dict:
                embed.description = "No command permissions configured"
            else:
                for cmd_name, cmd_config in commands_dict.items():
                    # Get command aliases if any
                    cmd = bot.get_command(cmd_name)
                    aliases_text = ""
                    if cmd and hasattr(cmd, 'aliases') and cmd.aliases:
                        aliases_text = f" (aliases: {', '.join([f'`{a}`' for a in cmd.aliases])})"

                    channels = cmd_config.get("channels", {})
                    channel_list = []

                    for chan_id, chan_config in channels.items():
                        if chan_id == "*":
                            channel_desc = "All channels"
                        else:
                            channel = bot.get_channel(int(chan_id))
                            channel_desc = f"#{channel.name}" if channel else f"ID:{chan_id}"

                        is_public = chan_config.get("public", False)
                        status = " (Public)" if is_public else f" ({len(chan_config.get('authorized_users', []))} users)"
                        channel_list.append(f"{channel_desc}{status}")

                    if channel_list:
                        embed.add_field(
                            name=f"Command: `{cmd_name}`{aliases_text}",
                            value="\n".join(channel_list[:5]) + (
                                f"\n...and {len(channel_list) - 5} more channels" if len(channel_list) > 5 else ""
                            ),
                            inline=False
                        )

            await ctx.send(embed=embed)

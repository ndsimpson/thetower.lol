import logging
from typing import Dict, Any
from discord.ext import commands
from discord.ext.commands import Context

from fish_bot.exceptions import ChannelUnauthorized, UserUnauthorized
from fish_bot.utils import ConfigManager


class BaseCog(commands.Cog):
    def __init__(self, bot):
        super().__init__()  # Initialize commands.Cog
        self.bot = bot
        self.config = ConfigManager()
        self._permissions = self.load_command_permissions()

    def load_command_permissions(self) -> Dict[str, Any]:
        """Load command permissions from configuration."""
        try:
            permissions = self.config.get("command_permissions", {"commands": {}})
            return permissions
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to load command permissions: {e}")
            return {"commands": {}}

    def get_command_name(self, ctx: Context) -> str:
        """Get the full command name including parent commands."""
        cmd = ctx.command
        parent = cmd.parent
        if parent is None:
            return cmd.name
        return f"{parent.name} {cmd.name}"

    async def cog_check(self, ctx: Context) -> bool:
        """Automatically check permissions for all commands in the cog."""
        if not ctx.command:
            return False

        # Skip permission checks for help command
        if ctx.command.name == 'help':
            return True

        # Check for wildcard command permission
        wildcard_config = self._permissions["commands"].get("*", {})
        if str(ctx.channel.id) in wildcard_config.get("channels", {}):
            return True

        command_name = self.get_command_name(ctx)
        command_config = self._permissions["commands"].get(command_name, {})
        channel_config = command_config.get("channels", {}).get(str(ctx.channel.id))

        # Check for wildcard channel permission
        if "*" in command_config.get("channels", {}):
            return True

        # Check channel permissions
        if not channel_config:
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Command '{command_name}' blocked - unauthorized channel. "
                f"Channel: {ctx.channel} (ID: {ctx.channel.id})"
            )
            raise ChannelUnauthorized(ctx.channel)

        # Check user permissions if channel is not public
        if not channel_config.get("public", False):
            if ctx.author.id not in channel_config.get("authorized_users", []):
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Command '{command_name}' blocked - unauthorized user. "
                    f"User: {ctx.author} (ID: {ctx.author.id})"
                )
                raise UserUnauthorized(ctx.author)

        return True

    def reload_permissions(self) -> None:
        """Reload permissions from file."""
        self._permissions = self.load_command_permissions()
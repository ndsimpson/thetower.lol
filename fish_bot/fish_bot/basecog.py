# Standard library imports
import logging
from pathlib import Path
from typing import Dict, Any

# Third-party imports
from discord.ext import commands
from discord.ext.commands import Context

# Local application imports
from fish_bot.exceptions import ChannelUnauthorized, UserUnauthorized
from fish_bot.utils import ConfigManager


class BaseCog(commands.Cog):
    def __init__(self, bot):
        super().__init__()  # Initialize commands.Cog
        self.bot = bot
        self.config = ConfigManager()
        self._permissions = self.load_command_permissions()
        self._guild = None  # Cache for guild object
        self._cog_data_directory = None  # Cache for cog data directory

        # Register for the reconnect event to clear the guild cache
        self.bot.add_listener(self.on_reconnect, 'on_resumed')

    async def on_reconnect(self):
        """Reset the guild cache when the bot reconnects."""
        self._guild = None
        logger = logging.getLogger(__name__)
        logger.debug(f"Guild cache reset for {self.__class__.__name__}")

    @property
    def guild(self):
        """Get and cache the primary guild for this bot."""
        if self._guild is None:
            self._guild = self.bot.get_guild(self.config.get_guild_id())
        return self._guild

    @property
    def data_directory(self) -> Path:
        """Get and cache the cog's data directory."""
        if self._cog_data_directory is None:
            cog_name = self.__class__.__name__
            self._cog_data_directory = self.config.get_cog_data_directory(cog_name)
        return self._cog_data_directory

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

    # Cog settings methods

    def get_setting(self, key: str, default: Any = None, guild_id: int = None) -> Any:
        """Get a cog-specific setting.

        Args:
            key: Setting name
            default: Default value if setting doesn't exist
            guild_id: Optional guild ID (uses current guild by default)

        Returns:
            The setting value or default

        Example:
            value = self.get_setting('timeout_seconds', 60)
        """
        cog_name = self.__class__.__name__
        return self.config.get_cog_setting(cog_name, key, default, guild_id)

    def set_setting(self, key: str, value: Any, guild_id: int = None) -> None:
        """Save a cog-specific setting.

        Args:
            key: Setting name
            value: Setting value
            guild_id: Optional guild ID (uses current guild by default)

        Example:
            self.set_setting('timeout_seconds', 120)
        """
        cog_name = self.__class__.__name__
        self.config.set_cog_setting(cog_name, key, value, guild_id)

    def update_settings(self, settings: Dict[str, Any], guild_id: int = None) -> None:
        """Update multiple cog settings at once.

        Args:
            settings: Dictionary of settings to update
            guild_id: Optional guild ID (uses current guild by default)

        Example:
            self.update_settings({
                'timeout_seconds': 120,
                'max_retries': 3,
                'enabled': True
            })
        """
        cog_name = self.__class__.__name__
        self.config.update_cog_settings(cog_name, settings, guild_id)

    def remove_setting(self, key: str, guild_id: int = None) -> bool:
        """Remove a cog-specific setting.

        Args:
            key: Setting name to remove
            guild_id: Optional guild ID (uses current guild by default)

        Returns:
            True if setting was removed, False if it didn't exist

        Example:
            self.remove_setting('legacy_option')
        """
        cog_name = self.__class__.__name__
        return self.config.remove_cog_setting(cog_name, key, guild_id)

    def has_setting(self, key: str, guild_id: int = None) -> bool:
        """Check if a cog-specific setting exists.

        Args:
            key: Setting name to check
            guild_id: Optional guild ID (uses current guild by default)

        Returns:
            True if setting exists, False otherwise

        Example:
            if self.has_setting('feature_enabled'):
                # use the feature
        """
        cog_name = self.__class__.__name__
        return self.config.has_cog_setting(cog_name, key, guild_id)

    def get_all_settings(self, guild_id: int = None) -> Dict[str, Any]:
        """Get all settings for this cog.

        Args:
            guild_id: Optional guild ID (uses current guild by default)

        Returns:
            Dictionary of all cog settings

        Example:
            all_settings = self.get_all_settings()
            print(f"Current configuration: {all_settings}")
        """
        cog_name = self.__class__.__name__
        return self.config.get_all_cog_settings(cog_name, guild_id)
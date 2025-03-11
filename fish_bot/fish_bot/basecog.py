# Standard library imports
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Union, Callable, Optional

# Third-party imports
from discord.ext import commands
from discord.ext.commands import Context

# Local application imports
from fish_bot.exceptions import ChannelUnauthorized, UserUnauthorized
from fish_bot.utils import ConfigManager
from fish_bot.utils.data_management import DataManager
from fish_bot.utils.command_helpers import (
    create_settings_command,
    create_set_command,
    add_settings_commands,
    register_settings_commands,
    add_standard_admin_commands
)


logger = logging.getLogger(__name__)


class BaseCog(commands.Cog):
    """
    Base class for all cogs with common functionality.

    Provides utilities for:
    - Command permission management
    - Settings management
    - Data persistence
    - Standard command interfaces
    - Ready state tracking
    """

    def __init__(self, bot):
        super().__init__()  # Initialize commands.Cog
        self.bot = bot
        self.config = ConfigManager()
        self._permissions = self.load_command_permissions()
        self._guild = None  # Cache for guild object
        self._cog_data_directory = None  # Cache for cog data directory

        # Data management components
        self._data_manager = DataManager()
        self._save_tasks = {}  # Store periodic save tasks

        # Ready state tracking
        self._ready = asyncio.Event()
        self._ready_task = None
        self._ready_timeout = 60  # Default timeout in seconds

        # Register for the reconnect event to clear the guild cache
        self.bot.add_listener(self.on_reconnect, 'on_resumed')
        self.bot.add_listener(self._on_ready, 'on_ready')

    async def _on_ready(self):
        """Internal handler for bot ready event."""
        # If there's no ready task, create one
        if not self._ready_task or self._ready_task.done():
            self._ready_task = self.bot.loop.create_task(self._initialize_cog())

    async def _initialize_cog(self):
        """Initialize the cog and set the ready event."""
        try:
            # Call the cog-specific initialization if it exists
            if hasattr(self, 'cog_initialize') and callable(self.cog_initialize):
                await self.cog_initialize()

            # Set the ready event to signal the cog is fully initialized
            self._ready.set()
            logger.info(f"Cog {self.__class__.__name__} is now ready")
        except Exception as e:
            logger.error(f"Error initializing cog {self.__class__.__name__}: {e}")
            # Don't set ready event on error

    async def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until the cog is ready to use.

        Args:
            timeout: Maximum time to wait in seconds. If None, uses the cog's default timeout.

        Returns:
            bool: True if the cog is ready, False if timed out
        """
        timeout = timeout if timeout is not None else self._ready_timeout
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Timed out waiting for cog {self.__class__.__name__} to become ready")
            return False

    @property
    def is_ready(self) -> bool:
        """Check if the cog is ready."""
        return self._ready.is_set()

    def set_ready_timeout(self, timeout: float) -> None:
        """
        Set the timeout for the ready event.

        Args:
            timeout: Timeout in seconds
        """
        self._ready_timeout = timeout

    async def on_reconnect(self):
        """Reset the guild cache when the bot reconnects."""
        self._guild = None
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

    # ----- Data Management Methods -----

    def mark_data_modified(self):
        """Mark the cog's data as modified, needing to be saved."""
        self._data_manager.mark_modified()

    def is_data_modified(self) -> bool:
        """Check if the cog's data has been modified."""
        return self._data_manager.is_modified()

    async def save_data_if_modified(self, data: Any, file_path: Union[str, Path], force: bool = False) -> bool:
        """
        Save data to file if it's been modified or if forced.

        Args:
            data: The data to save (must be JSON/pickle serializable)
            file_path: Path where the data should be saved
            force: Whether to save even if not modified

        Returns:
            bool: True if save was successful, False otherwise
        """
        return await self._data_manager.save_if_modified(data, file_path, force)

    async def load_data(self, file_path: Union[str, Path], default: Any = None) -> Any:
        """
        Load data from a file with fallback to default if file doesn't exist.

        Args:
            file_path: Path to the data file
            default: Default value to return if file doesn't exist

        Returns:
            The loaded data or default value
        """
        return await self._data_manager.load_data(file_path, default)

    async def create_periodic_save_task(self, data: Any, file_path: Union[str, Path], save_interval: int) -> asyncio.Task:
        """
        Create a task that periodically saves data.

        Args:
            data: The data to save (must be serializable)
            file_path: Path where the data should be saved
            save_interval: How often to save (in seconds)

        Returns:
            asyncio.Task: The created task
        """
        async def periodic_save():
            await self.bot.wait_until_ready()
            while not self.bot.is_closed():
                await asyncio.sleep(save_interval)
                await self.save_data_if_modified(data, file_path)

        # Cancel any existing task for this file
        file_key = str(file_path)
        if file_key in self._save_tasks and not self._save_tasks[file_key].done():
            self._save_tasks[file_key].cancel()

        # Create and store the new task
        task = self.bot.loop.create_task(periodic_save())
        self._save_tasks[file_key] = task
        return task

    def cancel_save_tasks(self):
        """Cancel all periodic save tasks."""
        for task in self._save_tasks.values():
            if not task.done():
                task.cancel()
        self._save_tasks.clear()

    # ----- Command Helper Methods -----

    def create_settings_command(self, group_command) -> Callable:
        """
        Create a standard settings display command.

        Args:
            group_command: The command group to add this command to

        Returns:
            The created command function
        """
        return create_settings_command(self)

    def create_set_command(self, valid_settings=None, validators=None) -> Callable:
        """
        Create a standard command for changing settings.

        Args:
            valid_settings: Optional list of valid setting names
            validators: Optional dict mapping setting names to validator functions

        Returns:
            The created command function
        """
        return create_set_command(self, valid_settings, validators)

    def add_settings_commands(self, group_command, valid_settings=None, validators=None):
        """
        Add both settings and set commands to a command group.

        Args:
            group_command: The command group to add commands to
            valid_settings: Optional list of valid setting names
            validators: Optional dict mapping setting names to validator functions
        """
        add_settings_commands(self, group_command, valid_settings, validators)

    def register_settings_commands(self, group_name, valid_settings=None, validators=None, aliases=None) -> commands.Group:
        """
        Register a complete settings command group for this cog.

        Args:
            group_name: Name for the command group
            valid_settings: Optional list of valid setting names
            validators: Optional dict mapping setting names to validator functions
            aliases: Optional list of aliases for the command group

        Returns:
            The created command group
        """
        return register_settings_commands(self, group_name, valid_settings, validators, aliases)

    def add_admin_commands(self, group_name, aliases=None) -> commands.Group:
        """
        Add standard administrative commands to this cog.

        Args:
            group_name: Name for the admin command group
            aliases: Optional aliases for the admin command group

        Returns:
            The created command group
        """
        return add_standard_admin_commands(self, group_name, aliases)

    # Utility method to get common time-based validators
    def get_time_validators(self, min_seconds=60) -> Dict[str, Callable]:
        """
        Get common validators for time-based settings.

        Args:
            min_seconds: Minimum allowed seconds

        Returns:
            Dict of validator functions for time settings
        """
        def time_validator(value):
            if not isinstance(value, (int, float)):
                return "Value must be a number"
            if value < min_seconds:
                return f"Value must be at least {min_seconds} seconds"
            return True

        return {
            name: time_validator for name in self.get_all_settings().keys()
            if name.endswith(('_interval', '_threshold', '_timeout', '_delay', '_duration'))
        }

    async def cog_unload(self):
        """Clean up resources when cog is unloaded."""
        # Cancel periodic save tasks
        self.cancel_save_tasks()

        # Cancel the ready task if it exists and is still running
        if self._ready_task and not self._ready_task.done():
            self._ready_task.cancel()

        # Clear the ready event
        self._ready.clear()

        # Force save any modified data
        if self.is_data_modified():
            logger.warning(f"Cog {self.__class__.__name__} has unsaved data on unload")

        # Call parent implementation if it exists
        if hasattr(super(), 'cog_unload'):
            await super().cog_unload()
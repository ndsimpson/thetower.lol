# Standard library imports
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any, Union, Callable, Optional
import datetime

# Third-party imports
import discord
from discord.ext import commands
from discord.ext.commands import Context

# Local application imports
from fish_bot.exceptions import ChannelUnauthorized, UserUnauthorized
from fish_bot.utils import ConfigManager
from fish_bot.utils.task_tracker import TaskTracker
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
    - Task status tracking
    - Logging
    """

    def __init__(self, bot):
        super().__init__()  # Initialize commands.Cog
        self.bot = bot
        self.config = ConfigManager()
        self._guild = None  # Cache for guild object
        self._cog_data_directory = None  # Cache for cog data directory
        self._has_errors = False  # Track if the cog has errors
        self._last_operation = None  # Track the last operation time
        self._operation_count = 0  # Track the number of operations
        self._is_paused = False  # Track if the cog is paused

        # Just get the logger, inheriting parent configuration
        self._logger = logging.getLogger(f"fish_bot.{self.__class__.__name__}")

        # Data management components
        self._data_manager = DataManager()
        self._save_tasks = {}  # Store periodic save tasks

        # Ready state tracking
        self._ready = asyncio.Event()
        self._ready_task = None
        self._ready_timeout = 60  # Default timeout in seconds
        self._is_ready = False

        # Initialize task tracker with the cog's logger
        self._task_tracker = TaskTracker(logger=self._logger, history_size=10)

        # Register for the reconnect event to clear the guild cache
        self.logger.debug(f"Registering listeners for {self.__class__.__name__}")
        self.bot.add_listener(self.on_reconnect, 'on_resumed')

        # Manually call _initialize_cog if bot is already ready
        if self.bot.is_ready():
            self.logger.debug("Bot already ready, initializing cog directly")
            self.bot.loop.create_task(self._initialize_cog())
        else:
            # Otherwise register for the ready event
            self.bot.add_listener(self._on_ready, 'on_ready')

        self.logger.debug(f"Registered listeners for {self.__class__.__name__}")

    @property
    def logger(self) -> logging.Logger:
        """
        Get the cog-specific logger.

        Returns:
            logging.Logger: Logger instance for this cog
        """
        return self._logger

    @property
    def task_tracker(self) -> TaskTracker:
        """
        Get the cog's task tracker.

        This provides direct access to the TaskTracker instance for tracking
        task execution, history, and statistics.

        Returns:
            TaskTracker: The task tracker instance
        """
        return self._task_tracker

    @property
    def is_paused(self) -> bool:
        """Check if the cog is currently paused."""
        return self._is_paused

    # Status command helper for task tracking
    def add_task_status_fields(self, embed: discord.Embed) -> None:
        """
        Add task tracking fields to a status embed.

        Args:
            embed: The discord Embed to add fields to
        """
        # Add active tasks
        active_tasks = self.task_tracker.get_active_tasks()
        if active_tasks:
            active_tasks_text = []
            for name, info in active_tasks.items():
                elapsed = self.format_relative_time(info['start_time'])
                active_tasks_text.append(f"🔄 **{name}**: {info['status']} (started {elapsed} ago)")

            if active_tasks_text:
                embed.add_field(
                    name="Active Processes",
                    value="\n".join(active_tasks_text),
                    inline=False
                )

        # Add recent task activity
        report = self.task_tracker.get_status_report()
        recent_activity = report.get('recent_activity', {})
        if recent_activity:
            for name, info in recent_activity.items():
                time_ago = self.format_relative_time(info['time'])
                status = "✅ Succeeded" if info['success'] else f"❌ Failed: {info['status']}"
                duration = self.task_tracker.format_task_time(info['execution_time'])

                embed.add_field(
                    name="Last Activity",
                    value=f"**{name}**: {status} ({time_ago} ago, took {duration})",
                    inline=False
                )
                break  # Just show the first recent activity

        # Add task statistics
        statistics = report.get('statistics', {})
        if statistics:
            stats_text = []
            for name, stats in statistics.items():
                if stats.get('total', 0) > 0:
                    success_rate = (stats.get('success', 0) / stats.get('total', 1)) * 100
                    avg_time = self.task_tracker.format_task_time(stats.get('avg_time', 0))
                    stats_text.append(
                        f"**{name}**: {stats.get('total', 0)} runs, "
                        f"{success_rate:.1f}% success, avg {avg_time}"
                    )

            if stats_text:
                embed.add_field(
                    name="Task Statistics",
                    value="\n".join(stats_text[:3]),  # Limit to 3 for readability
                    inline=False
                )

    async def _on_ready(self):
        """Internal handler for bot ready event."""
        # If there's no ready task, create one
        if not self._ready_task or self._ready_task.done():
            self._ready_task = self.bot.loop.create_task(self._initialize_cog())

    async def _initialize_cog(self):
        """Initialize the cog and set the ready event."""
        self.logger.debug(f"Starting _initialize_cog for {self.__class__.__name__}")
        try:
            # Call the cog-specific initialization if it exists
            if hasattr(self, 'cog_initialize') and callable(self.cog_initialize):
                self.logger.debug(f"Calling cog_initialize for {self.__class__.__name__}")
                await self.cog_initialize()
                self.logger.debug(f"Completed cog_initialize for {self.__class__.__name__}")
            else:
                self.logger.debug(f"No cog_initialize method found for {self.__class__.__name__}")

            # Set the ready event to signal the cog is fully initialized
            self._ready.set()
            self.logger.info(f"Cog {self.__class__.__name__} is now ready")
        except Exception as e:
            self.logger.error(f"Error initializing cog {self.__class__.__name__}: {e}", exc_info=True)
            # Don't set ready event on error

    async def cog_initialize(self) -> None:
        """Initialize cog-specific resources after bot is ready.

        This method should be overridden by cogs to perform async initialization.
        The base method handles command registration.
        """
        # Register commands based on their type settings
        await self.register_commands()

        # Command types will be properly set up before derived class initialization

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
            self.logger.warning(f"Timed out waiting for cog {self.__class__.__name__} to become ready")
            return False

    @property
    def is_ready(self) -> bool:
        """Check if the cog is ready for use."""
        return self._is_ready and self._ready.is_set()

    def set_ready(self, ready: bool = True) -> None:
        """Set the cog's ready state."""
        self._is_ready = ready
        if ready:
            self._ready.set()
        else:
            self._ready.clear()

    async def register_commands(self):
        """Register commands based on their type settings.

        This method should be called during cog initialization to register
        flexible commands according to their configured types.
        """
        self.logger.debug(f"Registering commands for {self.__class__.__name__}")

        # Process each command in the cog
        for command in self.get_commands():
            # Skip commands that don't have flex command attributes
            if not hasattr(command, "_flex_command_func"):
                continue

            command_name = command._flex_command_name
            command_type = self.bot.command_type_manager.get_command_type(command_name)

            self.logger.debug(f"Command {command_name} has type {command_type}")

            # Handle registration based on command type
            if command_type == "prefix":
                # Ensure it's not in the app command tree
                try:
                    self.bot.tree.remove_command(command_name)
                except Exception:
                    # Command might not exist in tree
                    pass

            elif command_type == "slash":
                # Remove as prefix command and add as app command
                # First store a reference to the command for later removal
                cmd_to_remove = self.bot.get_command(command_name)

                if cmd_to_remove:
                    self.bot.remove_command(command_name)

                # Register as app command
                kwargs = command._flex_command_kwargs.copy()
                # Remove aliases as they don't work with app commands
                if "aliases" in kwargs:
                    del kwargs["aliases"]

                # Register with the app command tree
                self.bot.tree.command(name=command_name, **kwargs)(
                    command._flex_command_func)

            elif command_type == "both":
                # Ensure it exists as both types
                kwargs = command._flex_command_kwargs.copy()
                # Remove aliases as they don't work with app commands
                if "aliases" in kwargs:
                    slash_kwargs = kwargs.copy()
                    del slash_kwargs["aliases"]
                else:
                    slash_kwargs = kwargs

                # Register with the app command tree if not already
                self.bot.tree.command(name=command_name, **slash_kwargs)(
                    command._flex_command_func)

            elif command_type == "none":
                # Remove from both systems
                try:
                    self.bot.remove_command(command_name)
                except Exception:
                    pass

                try:
                    self.bot.tree.remove_command(command_name)
                except Exception:
                    pass

        self.logger.info(f"Command registration completed for {self.__class__.__name__}")
        return True

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
        self.logger.debug(f"Guild cache reset for {self.__class__.__name__}")

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
            self.logger.error(f"Failed to load command permissions: {e}")
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

        # Get the full command name for subcommands
        command_name = self.get_command_name(ctx)

        # Use the bot's permission manager to check permissions
        try:
            return await self.bot.permission_manager.check_command_permissions(ctx, command_name)
        except (UserUnauthorized, ChannelUnauthorized):
            # Let these exceptions propagate for the error handler
            raise

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check permissions for slash commands.

        This is the slash command equivalent of cog_check.
        """
        if not interaction.command:
            return True

        # Create a mock context for permission manager
        ctx = SimpleNamespace(
            command=SimpleNamespace(name=interaction.command.name),
            bot=interaction.client,
            guild=interaction.guild,
            channel=interaction.channel,
            author=interaction.user,
            message=SimpleNamespace(channel_mentions=[])
        )

        try:
            await self.bot.permission_manager.check_command_permissions(ctx)
            return True
        except (UserUnauthorized, ChannelUnauthorized) as e:
            # Send error message as ephemeral response
            if isinstance(e, UserUnauthorized):
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command.",
                    ephemeral=True
                )
            elif isinstance(e, ChannelUnauthorized):
                await interaction.response.send_message(
                    "❌ This command cannot be used in this channel.",
                    ephemeral=True
                )
            return False

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

    def format_time_value(self, seconds: int) -> str:
        """Format seconds into a human-readable string.

        Args:
            seconds: Number of seconds

        Returns:
            str: Formatted string like "1h 30m 45s (5445 seconds)"
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs}s ({seconds} seconds)"

    def format_relative_time(self, timestamp) -> str:
        """Format a timestamp as a relative time string.

        Args:
            timestamp: Datetime object

        Returns:
            str: Human readable relative time (e.g., "5 minutes ago")
        """
        # Handle None values gracefully
        if timestamp is None:
            return "unknown time"

        now = datetime.datetime.now()

        # Handle timezone-aware timestamps
        if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo:
            if not now.tzinfo:
                now = now.replace(tzinfo=datetime.timezone.utc)

        diff = now - timestamp
        seconds = diff.total_seconds()

        if seconds < 60:
            return f"{int(seconds)} seconds ago"
        elif seconds < 3600:
            return f"{int(seconds // 60)} minutes ago"
        elif seconds < 86400:
            return f"{int(seconds // 3600)} hours ago"
        else:
            return f"{int(seconds // 86400)} days ago"

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
            self.logger.warning(f"Cog {self.__class__.__name__} has unsaved data on unload")

        # Call parent implementation if it exists
        if hasattr(super(), 'cog_unload'):
            await super().cog_unload()

    async def _handle_toggle(
        self,
        ctx: commands.Context,
        setting_name: str,
        value: Optional[bool] = None,
        *,
        description: Optional[str] = None
    ) -> None:
        """Handle toggling a boolean setting.

        Args:
            ctx: Command context (works with both prefix and slash commands)
            setting_name: Name of the setting to toggle
            value: Optional explicit value to set
            description: Optional description of what is being toggled (for better UX)
        """
        if setting_name not in self.get_all_settings():
            await ctx.send(f"❌ Unknown setting: {setting_name}")
            return

        current = self.get_setting(setting_name)
        if not isinstance(current, bool):
            await ctx.send(f"❌ Setting {setting_name} is not toggleable")
            return

        new_value = not current if value is None else value
        self.set_setting(setting_name, new_value)

        # Format the setting name for display
        display_name = description or setting_name.replace('_', ' ').title()

        emoji = "✅" if new_value else "❌"
        await ctx.send(f"{emoji} {display_name} is now {'enabled' if new_value else 'disabled'}")

        # Log the change
        self.logger.info(f"Setting toggled: {setting_name} = {new_value} by {ctx.author}")

        # Mark settings as modified
        self.mark_data_modified()

    async def _handle_pause(
        self,
        ctx: Union[commands.Context, discord.Interaction],
        state: Optional[bool] = None,
        *,
        description: Optional[str] = None
    ) -> None:
        """Handle pausing/unpausing cog operations.

        Args:
            ctx: Command context or interaction
            state: Optional explicit pause state, toggles if None
            description: Optional description of what is being paused
        """
        # Toggle if no state specified
        new_state = not self._is_paused if state is None else state
        old_state = self._is_paused
        self._is_paused = new_state

        # Only send message if state actually changed
        if new_state != old_state:
            display_name = description or f"{self.__class__.__name__} Operations"
            status = "⏸️ Paused" if new_state else "▶️ Resumed"

            msg = f"{status}: {display_name}"

            # Handle both context and interaction responses
            if isinstance(ctx, discord.Interaction):
                if ctx.response.is_done():
                    await ctx.followup.send(msg)
                else:
                    await ctx.response.send_message(msg)
            else:
                await ctx.send(msg)

            # Log the change
            self.logger.info(
                f"{self.__class__.__name__} {'paused' if new_state else 'resumed'} "
                f"by {ctx.author if hasattr(ctx, 'author') else ctx.user}"
            )

    def create_pause_commands(self, group_command) -> None:
        """Add pause/resume commands to a command group.

        Args:
            group_command: The command group to add commands to
        """

        @group_command.command(name="pause")
        async def pause(ctx):
            """Pause operations"""
            await self._handle_pause(ctx, True)

        @group_command.command(name="resume")
        async def resume(ctx):
            """Resume operations"""
            await self._handle_pause(ctx, False)

        @group_command.command(name="toggle")
        async def toggle(ctx):
            """Toggle pause state"""
            await self._handle_pause(ctx)
